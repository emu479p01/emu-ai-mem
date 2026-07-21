from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from emu_ai_mem.config import VaultConfig, load_config, save_config
from emu_ai_mem.errors import RecordError
from emu_ai_mem.records import MemoryRecord, generate_id, write_record


def test_config_round_trip_isolated_by_home(app_home: Path) -> None:
    config = load_config()
    config.author_name = "Chaiyaporn Santangjai"
    config.vaults["personal"] = VaultConfig(
        "personal", "git@example/personal.git", app_home / "vault", "personal"
    )
    config.default_vault = "personal"
    save_config(config)

    loaded = load_config()
    assert loaded.author_name == "Chaiyaporn Santangjai"
    assert loaded.default_vault == "personal"
    assert loaded.vaults["personal"].path == app_home / "vault"


def test_ids_are_unique_across_concurrent_writers() -> None:
    now = datetime(2026, 7, 21, tzinfo=UTC)
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: generate_id("chai", "laptop", now=now), range(200)))
    assert len(ids) == len(set(ids))
    assert all(item.startswith("20260721T000000") for item in ids)


def test_append_only_write_refuses_overwrite(tmp_path: Path) -> None:
    record = MemoryRecord(
        id="20260721T000000000000Z-chai-device-abc123",
        project="engine",
        tags=["decision"],
        created_at="2026-07-21T00:00:00Z",
        author_id="chai",
        author_name="Chai",
        device_id="device",
        scope="personal",
        summary="Keep history",
        details="Use supersedes.",
    )
    path = write_record(tmp_path, record)
    assert MemoryRecord.from_path(path).summary == "Keep history"
    with pytest.raises(RecordError, match="Refusing to overwrite"):
        write_record(tmp_path, record)


def test_record_validation_rejects_scope() -> None:
    record = MemoryRecord(
        id="id",
        project="p",
        tags=[],
        created_at="2026-07-21T00:00:00Z",
        author_id="a",
        author_name="A",
        device_id="d",
        scope="secret",
        summary="summary",
        details="",
    )
    with pytest.raises(RecordError, match="scope"):
        record.validate()
