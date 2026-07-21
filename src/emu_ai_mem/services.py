from __future__ import annotations

import shutil
from pathlib import Path

import frontmatter

from .config import AppConfig
from .errors import RecordError
from .gitops import commit_paths, is_pending, sync_vault
from .index import rebuild_index
from .paths import cache_dir, config_path, data_dir, state_path
from .records import MemoryRecord, create_record, split_body, string_list, write_record
from .store import connect as connect_store
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


def note(
    config: AppConfig,
    text: str,
    *,
    project: str = "general",
    tags: list[str] | None = None,
    details: str = "",
    category: str = "sessions",
    vault_name: str | None = None,
    auto_sync: bool = True,
) -> tuple[Path, str]:
    """Persist an explicitly selected note without depending on a working directory."""
    summary = text.strip()
    if not summary:
        raise RecordError("Note text cannot be empty")
    return remember(
        config,
        project=project.strip() or "general",
        tags=tags or [],
        summary=summary,
        details=details,
        category=category,
        vault_name=vault_name,
        auto_sync=auto_sync,
    )


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


GENERIC_INSTRUCTIONS = """# emu-ai-mem v2 integration

Use the bounded continuation capsule when one is supplied. Search on demand with
`emu-mem search \"<topic>\"`; do not search every prompt.

Save an explicitly selected durable fact or decision with:

`emu-mem remember --summary \"<durable fact or decision>\" --project <name> --kind <kind>`

Use `emu-mem supersede <id> ...` instead of editing an immutable event. Never copy raw
transcripts or secrets into memory. Automatic checkpoints belong to a personal vault; publish a
team handoff only with explicit user authorization. Run `emu-mem doctor` on failures.
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
    messages.append(f"database: {state_path()}")
    try:
        db = connect_store()
        schema_version = db.execute("PRAGMA user_version").fetchone()[0]
        queued = db.execute("SELECT count(*) FROM outbox").fetchone()[0]
        semantic_queued = db.execute("SELECT count(*) FROM semantic_queue").fetchone()[0]
        db.close()
        messages.append(
            f"database schema: {schema_version}; pending events: {queued}; "
            f"semantic queue: {semantic_queued}"
        )
        healthy &= schema_version == 2
    except Exception as exc:
        messages.append(f"database: unhealthy: {exc}")
        healthy = False
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
    if not any(vault.kind == "personal" for vault in config.vaults.values()):
        messages.append("personal vault: missing; automatic session checkpoints are disabled")
    if not config.default_vault:
        messages.append("default vault: not set")
        healthy = False
    else:
        messages.append(f"default vault: {config.default_vault}")
    return bool(healthy), messages


def hook(event: str, stdin_text: str) -> tuple[int, str]:
    """Deprecated v1 hook shim; v2 never searches on every user prompt."""
    if event == "session-start":
        return 0, "emu-ai-mem v2 ready; use the client-specific session-start hook."
    if event == "prompt":
        return 0, ""
    if event in {"pre-compact", "stop"}:
        return 0, (
            "Before context is lost, save only durable facts or decisions with `emu-mem note`. "
            "Do not store raw transcripts or secrets."
        )
    return 0, ""
