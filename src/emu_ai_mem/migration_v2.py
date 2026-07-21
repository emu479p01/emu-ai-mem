from __future__ import annotations

import hashlib
from pathlib import Path

from .config import AppConfig
from .records import MemoryRecord, iter_record_paths
from .store import connect, remember_memory, transaction, utc_now


def migrate_v1(
    config: AppConfig,
    source: Path,
    *,
    vault_name: str,
    db_path: Path | None = None,
) -> tuple[int, list[str]]:
    """Import v1 Markdown without modifying the source tree."""
    if vault_name not in config.vaults:
        raise ValueError(f"Unknown vault: {vault_name}")
    imported = 0
    warnings: list[str] = []
    for path in iter_record_paths(source.expanduser().resolve()):
        relative = path.relative_to(source).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        db = connect(db_path)
        try:
            known = db.execute(
                "SELECT 1 FROM migration_sources WHERE vault=? AND source_path=? AND content_hash=?",
                (vault_name, relative, digest),
            ).fetchone()
        finally:
            db.close()
        if known:
            continue
        try:
            record = MemoryRecord.from_path(path)
            db = connect(db_path)
            try:
                entity_exists = db.execute(
                    "SELECT 1 FROM memories WHERE id=?", (record.id,)
                ).fetchone()
            finally:
                db.close()
            if not entity_exists:
                remember_memory(
                    config,
                    vault_name=vault_name,
                    project=record.project,
                    summary=record.summary,
                    details=record.details,
                    kind={
                        "decisions": "decision",
                        "sessions": "session-note",
                        "projects": "fact",
                    }[record.category],
                    tags=(*record.tags, f"v1-category:{record.category}"),
                    supersedes=record.supersedes,
                    memory_id=record.id,
                    created_at=record.created_at,
                    provenance=f"v1:{relative}",
                    db_path=db_path,
                )
            with transaction(db_path) as tx:
                tx.execute(
                    "INSERT OR IGNORE INTO migration_sources VALUES(?,?,?,?,?)",
                    (vault_name, relative, digest, record.id, utc_now()),
                )
            imported += int(not entity_exists)
        except Exception as exc:
            warnings.append(f"Could not import {path}: {exc}")
    return imported, warnings


def import_attached_v1_vaults(
    config: AppConfig, *, db_path: Path | None = None
) -> tuple[int, list[str]]:
    total = 0
    warnings: list[str] = []
    for vault in config.vaults.values():
        count, current = migrate_v1(
            config, vault.path, vault_name=vault.name, db_path=db_path
        )
        total += count
        warnings.extend(current)
    return total, warnings
