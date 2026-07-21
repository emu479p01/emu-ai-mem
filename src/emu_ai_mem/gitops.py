from __future__ import annotations

import subprocess
import time
from pathlib import Path

from filelock import FileLock, Timeout

from .errors import SyncError
from .paths import cache_dir, pending_dir


def run_git(
    path: Path,
    *args: str,
    check: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise SyncError(f"git {' '.join(args)} failed in {path}: {message}")
    return result


def clone_vault(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and any(destination.iterdir()):
        raise SyncError(f"Destination is not empty: {destination}")
    result = subprocess.run(
        ["git", "clone", url, str(destination)], capture_output=True, text=True, timeout=180
    )
    if result.returncode != 0:
        raise SyncError(f"git clone failed: {(result.stderr or result.stdout).strip()}")
    branch = run_git(destination, "branch", "--show-current").stdout.strip()
    if not branch:
        run_git(destination, "switch", "-c", "main")


def _pending_marker(name: str) -> Path:
    return pending_dir() / f"{name}.txt"


def mark_pending(name: str, message: str) -> None:
    _pending_marker(name).write_text(message.strip() + "\n", encoding="utf-8")


def clear_pending(name: str) -> None:
    marker = _pending_marker(name)
    if marker.exists():
        marker.unlink()


def is_pending(name: str) -> bool:
    return _pending_marker(name).exists()


def commit_paths(path: Path, paths: list[Path], message: str) -> bool:
    if not paths:
        return False
    rel_paths = [str(item.relative_to(path)) for item in paths]
    run_git(path, "add", "--", *rel_paths)
    changed = run_git(path, "diff", "--cached", "--quiet", check=False)
    if changed.returncode == 0:
        return False
    run_git(path, "commit", "-m", message)
    return True


def _has_origin_head(path: Path) -> bool:
    return run_git(path, "rev-parse", "--verify", "origin/main", check=False).returncode == 0


def _ensure_safe_worktree(path: Path) -> None:
    status = run_git(path, "status", "--porcelain").stdout.strip()
    if status:
        raise SyncError(
            "Vault has uncommitted changes. emu-ai-mem will not rebase or discard them. "
            f"Resolve them in {path}, then run `emu-mem sync` again.\n{status}"
        )


def sync_vault(name: str, path: Path, *, retries: int = 3) -> str:
    lock_path = cache_dir() / "locks" / f"{name}.lock"
    try:
        lock = FileLock(lock_path, timeout=30)
        with lock:
            _ensure_safe_worktree(path)
            last_error = ""
            for attempt in range(1, retries + 1):
                fetch = run_git(path, "fetch", "origin", check=False)
                if fetch.returncode != 0:
                    last_error = (fetch.stderr or fetch.stdout).strip()
                    mark_pending(name, last_error)
                    if attempt < retries:
                        time.sleep(0.2 * attempt)
                        continue
                    return f"pending: {last_error}"

                if _has_origin_head(path):
                    rebase = run_git(path, "rebase", "origin/main", check=False)
                    if rebase.returncode != 0:
                        conflict = (rebase.stderr or rebase.stdout).strip()
                        run_git(path, "rebase", "--abort", check=False)
                        mark_pending(name, conflict)
                        raise SyncError(
                            "Automatic rebase stopped and was aborted without discarding your commit. "
                            f"Resolve the history manually in {path}. Details: {conflict}"
                        )

                push = run_git(path, "push", "-u", "origin", "HEAD:main", check=False)
                if push.returncode == 0:
                    clear_pending(name)
                    return "synced"
                last_error = (push.stderr or push.stdout).strip()
                if attempt < retries:
                    time.sleep(0.2 * attempt)
                    continue
            mark_pending(name, last_error)
            return f"pending: {last_error}"
    except Timeout as exc:
        raise SyncError(f"Vault {name!r} is busy on this machine; retry later") from exc


def ensure_git_identity(path: Path, author_name: str, author_id: str) -> None:
    if not run_git(path, "config", "user.name", check=False).stdout.strip():
        run_git(path, "config", "user.name", author_name)
    if not run_git(path, "config", "user.email", check=False).stdout.strip():
        run_git(path, "config", "user.email", f"{author_id}@users.noreply.github.com")
