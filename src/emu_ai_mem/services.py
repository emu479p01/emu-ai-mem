from __future__ import annotations

import json
import shutil
from pathlib import Path

import frontmatter

from .config import AppConfig, load_config
from .errors import RecordError
from .gitops import commit_paths, is_pending, sync_vault
from .index import rebuild_index, search_index
from .paths import cache_dir, config_path, data_dir, index_path
from .records import MemoryRecord, create_record, split_body, string_list, write_record
from .vaults import resolve_vault


def remember(
    config: AppConfig,
    *,
    project: str,
    tags: list[str],
    summary: str,
    details: str,
    category: str,
    vault_name: str | None = None,
    supersedes: list[str] | None = None,
    auto_sync: bool = True,
) -> tuple[Path, str]:
    vault = resolve_vault(config, vault_name)
    record = create_record(
        config,
        project=project,
        tags=tags,
        scope=vault.kind,
        summary=summary,
        details=details,
        category=category,
        supersedes=supersedes,
    )
    path = write_record(vault.path, record)
    commit_paths(vault.path, [path], f"memory: {record.id}")
    sync_status = sync_vault(vault.name, vault.path) if auto_sync else "committed locally"
    rebuild_index(config)
    return path, sync_status


def find_record(
    config: AppConfig, memory_id: str, vault_name: str | None = None
) -> tuple[str, MemoryRecord]:
    matches: list[tuple[str, MemoryRecord]] = []
    candidates = [resolve_vault(config, vault_name)] if vault_name else list(config.vaults.values())
    for vault in candidates:
        for path in (vault.path / "memories").rglob(f"{memory_id}.md"):
            matches.append((vault.name, MemoryRecord.from_path(path)))
    if not matches:
        raise RecordError(f"Memory not found: {memory_id}")
    if len(matches) > 1:
        raise RecordError("Memory ID exists in multiple vaults; pass --vault")
    return matches[0]


def migrate_legacy(
    config: AppConfig,
    source: Path,
    *,
    vault_name: str | None = None,
    auto_sync: bool = True,
) -> tuple[int, list[str]]:
    vault = resolve_vault(config, vault_name)
    paths = (
        sorted((source / "memories").rglob("*.md"))
        if (source / "memories").exists()
        else sorted(source.rglob("*.md"))
    )
    written: list[Path] = []
    warnings: list[str] = []
    for path in paths:
        try:
            post = frontmatter.load(path)
            summary, details = split_body(post.content)
            meta = post.metadata
            record = create_record(
                config,
                project=str(meta.get("project") or "legacy-import"),
                tags=string_list(meta.get("tags", [])) + [f"legacy-id:{meta.get('id', path.stem)}"],
                scope=vault.kind,
                summary=summary or f"Imported {path.name}",
                details=details,
                category=path.parent.name
                if path.parent.name in {"projects", "sessions", "decisions"}
                else "sessions",
            )
            written.append(write_record(vault.path, record))
        except Exception as exc:
            warnings.append(f"Skipped {path}: {exc}")
    if written:
        commit_paths(vault.path, written, f"Import {len(written)} legacy memories")
        if auto_sync:
            status = sync_vault(vault.name, vault.path)
            if status.startswith("pending"):
                warnings.append(status)
    rebuild_index(config)
    return len(written), warnings


GENERIC_INSTRUCTIONS = """# emu-ai-mem integration

Before unfamiliar work, run `emu-mem search \"<topic>\"` and use relevant results as context.

At natural checkpoints, save durable project facts or decisions with:

`emu-mem remember --project <name> --tags <comma-separated> --summary \"...\" --details \"...\"`

Use `emu-mem supersede <id> ...` instead of editing a synced memory file. Never copy raw
transcripts or secrets into shared memory. Run `emu-mem doctor` when sync or configuration fails.
"""


def install_generic(project: Path) -> Path:
    target_dir = project.resolve() / ".emu-ai-mem"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "AGENT_INSTRUCTIONS.md"
    target.write_text(GENERIC_INSTRUCTIONS, encoding="utf-8")
    return target


def doctor(config: AppConfig) -> tuple[bool, list[str]]:
    messages: list[str] = []
    healthy = True
    git = shutil.which("git")
    messages.append(f"git: {git or 'NOT FOUND'}")
    healthy &= git is not None
    messages.append(f"config: {config_path()}")
    messages.append(f"data: {data_dir()}")
    messages.append(f"cache: {cache_dir()}")
    messages.append(f"index: {index_path()}")
    if not config.vaults:
        messages.append("vaults: none configured")
        healthy = False
    for vault in config.vaults.values():
        repo_ok = (vault.path / ".git").exists()
        pending = is_pending(vault.name)
        messages.append(
            f"vault {vault.name}: {'ok' if repo_ok else 'missing clone'}; "
            f"kind={vault.kind}; pending_push={'yes' if pending else 'no'}"
        )
        healthy &= repo_ok
    if not config.default_vault:
        messages.append("default vault: not set")
        healthy = False
    else:
        messages.append(f"default vault: {config.default_vault}")
    return bool(healthy), messages


def hook(event: str, stdin_text: str) -> tuple[int, str]:
    """Client-neutral hook entrypoint. Never stores a raw transcript."""
    try:
        config = load_config()
    except Exception as exc:
        return 0, f"emu-ai-mem is not configured: {exc}"
    if event == "session-start":
        statuses = []
        for vault in config.vaults.values():
            try:
                statuses.append(f"{vault.name}: {sync_vault(vault.name, vault.path)}")
            except Exception as exc:
                statuses.append(f"{vault.name}: sync warning: {exc}")
        try:
            rebuild_index(config)
        except Exception as exc:
            statuses.append(f"index warning: {exc}")
        return 0, "emu-ai-mem ready. " + "; ".join(statuses)
    if event == "prompt":
        try:
            payload = json.loads(stdin_text or "{}")
        except json.JSONDecodeError:
            payload = {}
        prompt = str(payload.get("prompt") or payload.get("user_prompt") or "").strip()
        if not prompt:
            return 0, ""
        try:
            results, _ = search_index(config, prompt, limit=3)
            if not results:
                return 0, ""
            lines = ["Relevant emu-ai-mem context (verify before relying on it):"]
            lines.extend(f"- [{item.vault}] {item.id}: {item.summary}" for item in results)
            return 0, "\n".join(lines)
        except Exception as exc:
            return 0, f"emu-ai-mem search warning: {exc}"
    if event in {"pre-compact", "stop"}:
        return 0, (
            "Before context is lost, save only durable facts or decisions with `emu-mem remember`. "
            "Do not store raw transcripts or secrets."
        )
    return 0, ""
