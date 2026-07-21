from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from .config import AppConfig, VaultConfig
from .gitops import commit_paths, sync_vault
from .store import apply_imported_event, connect, event_dict, transaction, utc_now


def _segment_directory(vault: VaultConfig, device_id: str) -> Path:
    month = datetime.now(UTC).strftime("%Y-%m")
    return vault.path / "events" / "v2" / device_id / month


def export_outbox(
    config: AppConfig, vault: VaultConfig, *, db_path: Path | None = None
) -> Path | None:
    db = connect(db_path)
    try:
        rows = db.execute(
            "SELECT e.* FROM outbox o JOIN events e ON e.id=o.event_id "
            "WHERE e.vault=? AND e.exported_segment IS NULL ORDER BY e.created_at,e.id",
            (vault.name,),
        ).fetchall()
    finally:
        db.close()
    if not rows:
        return None
    directory = _segment_directory(vault, config.device_id)
    directory.mkdir(parents=True, exist_ok=True)
    segment_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}-{config.device_id}"
    target = directory / f"{segment_id}.jsonl"
    temporary = target.with_suffix(".tmp")
    content = "".join(
        json.dumps(event_dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for row in rows
    )
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, target)
    return target


def _segment_event_ids(path: Path) -> list[str]:
    return [
        str(json.loads(line)["id"])
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def _finalize_export(vault: VaultConfig, path: Path, *, db_path: Path | None = None) -> None:
    relative = path.relative_to(vault.path).as_posix()
    identifiers = _segment_event_ids(path)
    with transaction(db_path) as tx:
        tx.executemany(
            "UPDATE events SET exported_segment=? WHERE id=?",
            [(relative, identifier) for identifier in identifiers],
        )
        tx.executemany(
            "DELETE FROM outbox WHERE event_id=?", [(identifier,) for identifier in identifiers]
        )


def _recover_pending_exports(vault: VaultConfig, *, db_path: Path | None = None) -> None:
    root = vault.path / "events" / "v2"
    if not root.exists():
        return
    db = connect(db_path)
    try:
        pending = {str(row[0]) for row in db.execute("SELECT event_id FROM outbox").fetchall()}
    finally:
        db.close()
    for path in sorted(root.rglob("*.jsonl")):
        try:
            if pending.intersection(_segment_event_ids(path)):
                commit_paths(vault.path, [path], f"events: recover {path.stem}")
                _finalize_export(vault, path, db_path=db_path)
        except (KeyError, ValueError, json.JSONDecodeError):
            continue


def import_segments(
    vault: VaultConfig, *, db_path: Path | None = None
) -> tuple[int, list[str]]:
    root = vault.path / "events" / "v2"
    if not root.exists():
        return 0, []
    imported = 0
    warnings: list[str] = []
    for path in sorted(root.rglob("*.jsonl")):
        relative = path.relative_to(vault.path).as_posix()
        content = path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        db = connect(db_path)
        try:
            known = db.execute(
                "SELECT content_hash FROM imported_segments WHERE vault=? AND segment_id=?",
                (vault.name, relative),
            ).fetchone()
        finally:
            db.close()
        if known:
            if str(known["content_hash"]) != digest:
                warnings.append(f"Immutable segment changed and was ignored: {relative}")
            continue
        try:
            events = [json.loads(line) for line in content.decode("utf-8").splitlines() if line]
            if any(event.get("schema_version") != 2 for event in events):
                raise ValueError("unsupported schema_version")
            with transaction(db_path) as tx:
                for event in events:
                    imported += int(apply_imported_event(tx, event))
                tx.execute(
                    "INSERT INTO imported_segments VALUES(?,?,?,?)",
                    (vault.name, relative, digest, utc_now()),
                )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            warnings.append(f"Invalid segment quarantined logically {relative}: {exc}")
    return imported, warnings


def sync_vault_events(
    config: AppConfig, vault: VaultConfig, *, db_path: Path | None = None
) -> tuple[str, int, list[str]]:
    _recover_pending_exports(vault, db_path=db_path)
    exported = export_outbox(config, vault, db_path=db_path)
    if exported:
        commit_paths(vault.path, [exported], f"events: {exported.stem}")
        _finalize_export(vault, exported, db_path=db_path)
    status = sync_vault(vault.name, vault.path)
    imported, warnings = import_segments(vault, db_path=db_path)
    # Mixed-version transition is read-only: discover new v1 Markdown after pull,
    # project it into v2, and export its v2 event at the next sync boundary.
    from .migration_v2 import migrate_v1

    v1_imported, v1_warnings = migrate_v1(
        config, vault.path, vault_name=vault.name, db_path=db_path
    )
    imported += v1_imported
    warnings.extend(v1_warnings)
    with transaction(db_path) as db:
        db.execute(
            "INSERT INTO sync_state(vault,last_sync_at,last_status) VALUES(?,?,?) "
            "ON CONFLICT(vault) DO UPDATE SET "
            "last_sync_at=excluded.last_sync_at,last_status=excluded.last_status",
            (vault.name, utc_now(), status),
        )
    return status, imported, warnings


def sync_all_events(
    config: AppConfig, *, vault_name: str | None = None, db_path: Path | None = None
) -> dict[str, dict[str, object]]:
    if vault_name and vault_name not in config.vaults:
        raise ValueError(f"Unknown vault: {vault_name}")
    selected = [config.vaults[vault_name]] if vault_name else list(config.vaults.values())
    result: dict[str, dict[str, object]] = {}
    for vault in selected:
        status, imported, warnings = sync_vault_events(config, vault, db_path=db_path)
        result[vault.name] = {"status": status, "imported": imported, "warnings": warnings}
    return result
