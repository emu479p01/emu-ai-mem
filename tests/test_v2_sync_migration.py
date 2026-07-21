from __future__ import annotations

from pathlib import Path

from emu_ai_mem.config import AppConfig, VaultConfig
from emu_ai_mem.migration_v2 import migrate_v1
from emu_ai_mem.records import MemoryRecord, write_record
from emu_ai_mem.store import remember_memory, search_memories
from emu_ai_mem.sync_v2 import export_outbox, import_segments


def test_event_segment_round_trip_is_idempotent(tmp_path: Path) -> None:
    first_path = tmp_path / "first"
    second_path = tmp_path / "second"
    first_path.mkdir()
    second_path.mkdir()
    first = AppConfig(
        "alice", "Alice", "laptop", default_vault="personal",
        vaults={"personal": VaultConfig("personal", "unused", first_path, "personal")},
    )
    second = AppConfig(
        "alice", "Alice", "desktop", default_vault="personal",
        vaults={"personal": VaultConfig("personal", "unused", second_path, "personal")},
    )
    db_one = tmp_path / "one.db"
    db_two = tmp_path / "two.db"
    memory = remember_memory(
        first, vault_name="personal", project="p", summary="portable event", db_path=db_one
    )
    segment = export_outbox(first, first.vaults["personal"], db_path=db_one)
    assert segment
    destination = second_path / segment.relative_to(first_path)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(segment.read_bytes())
    assert import_segments(second.vaults["personal"], db_path=db_two)[0] == 1
    assert import_segments(second.vaults["personal"], db_path=db_two)[0] == 0
    assert search_memories("portable", db_path=db_two)[0].id == memory.id


def test_v1_migration_preserves_source_and_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "source"
    vault = tmp_path / "vault"
    vault.mkdir()
    record = MemoryRecord(
        id="legacy-id",
        project="engine",
        tags=["legacy"],
        created_at="2026-07-21T00:00:00Z",
        author_id="alice",
        author_name="Alice",
        device_id="old",
        scope="personal",
        summary="legacy durable fact",
        details="details",
        category="decisions",
    )
    path = write_record(source, record)
    original = path.read_bytes()
    config = AppConfig(
        "alice", "Alice", "new", default_vault="personal",
        vaults={"personal": VaultConfig("personal", "unused", vault, "personal")},
    )
    db_path = tmp_path / "state.db"
    assert migrate_v1(config, source, vault_name="personal", db_path=db_path)[0] == 1
    assert migrate_v1(config, source, vault_name="personal", db_path=db_path)[0] == 0
    assert path.read_bytes() == original
    found = search_memories("legacy durable", db_path=db_path)
    assert found[0].id == "legacy-id"
    assert found[0].kind == "decision"
