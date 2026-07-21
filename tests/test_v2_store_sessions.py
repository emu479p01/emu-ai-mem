from __future__ import annotations

from pathlib import Path

import pytest

from emu_ai_mem.config import AppConfig, VaultConfig
from emu_ai_mem.errors import ConfigurationError, RecordError
from emu_ai_mem.store import (
    checkpoint_session,
    connect,
    open_session,
    publish_handoff,
    remember_memory,
    search_memories,
)


def _config(tmp_path: Path, *, team: bool = True) -> AppConfig:
    personal = tmp_path / "personal"
    personal.mkdir()
    vaults = {"personal": VaultConfig("personal", "unused", personal, "personal")}
    if team:
        team_path = tmp_path / "team"
        team_path.mkdir()
        vaults["team"] = VaultConfig("team", "unused", team_path, "team")
    return AppConfig("alice", "Alice", "laptop", default_vault="personal", vaults=vaults)


def test_memory_write_is_transactional_and_fts_is_incremental(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    config = _config(tmp_path)
    result = remember_memory(
        config,
        vault_name="personal",
        project="billing",
        summary="Use idempotency keys",
        kind="decision",
        db_path=db_path,
    )
    found = search_memories("idempotency", db_path=db_path)
    assert [item.id for item in found] == [result.id]
    db = connect(db_path)
    try:
        event = db.execute("SELECT id FROM events WHERE entity_id=?", (result.id,)).fetchone()
        assert event
        assert db.execute("SELECT 1 FROM outbox WHERE event_id=?", (event["id"],)).fetchone()
    finally:
        db.close()


def test_checkpoint_is_bounded_idempotent_and_personal(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    config = _config(tmp_path)
    session = open_session(
        config,
        provider="codex",
        provider_session_id="provider-session",
        cwd=tmp_path,
        db_path=db_path,
    )
    state = {
        "objective": "ship v2 " * 500,
        "state": "working",
        "decisions": [f"decision {index}" for index in range(100)],
        "next_steps": ["test", "publish"],
    }
    first = checkpoint_session(
        config,
        session_id=session.session_id,
        turn_id="turn-1",
        structured_state=state,
        db_path=db_path,
    )
    second = checkpoint_session(
        config,
        session_id=session.session_id,
        turn_id="turn-1",
        structured_state=state,
        db_path=db_path,
    )
    assert first["estimated_tokens"] <= 600
    assert second["checkpoint_id"] == first["checkpoint_id"]
    assert second["idempotent"] is True
    db = connect(db_path)
    try:
        assert db.execute(
            "SELECT vault FROM checkpoints WHERE id=?", (first["checkpoint_id"],)
        ).fetchone()["vault"] == "personal"
    finally:
        db.close()


def test_checkpoint_never_falls_back_to_team(tmp_path: Path) -> None:
    team = tmp_path / "team"
    team.mkdir()
    config = AppConfig(
        "alice",
        "Alice",
        "laptop",
        default_vault="team",
        vaults={"team": VaultConfig("team", "unused", team, "team")},
    )
    with pytest.raises(ConfigurationError, match="personal vault"):
        open_session(
            config,
            provider="codex",
            provider_session_id="session",
            cwd=tmp_path,
            db_path=tmp_path / "state.db",
        )


def test_team_handoff_is_an_explicit_new_memory(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    config = _config(tmp_path)
    session = open_session(
        config,
        provider="codex",
        provider_session_id="session",
        cwd=tmp_path,
        db_path=db_path,
    )
    checkpoint = checkpoint_session(
        config,
        session_id=session.session_id,
        turn_id="turn",
        structured_state={"objective": "handoff objective", "next_steps": ["review"]},
        db_path=db_path,
    )
    handoff = publish_handoff(
        config,
        checkpoint_id=checkpoint["checkpoint_id"],
        team_vault="team",
        project="engine",
        db_path=db_path,
    )
    assert handoff.vault == "team"
    assert handoff.kind == "handoff"
    assert handoff.provenance == f"checkpoint:{checkpoint['checkpoint_id']}"


def test_checkpoint_redacts_credentials_and_memory_rejects_them(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    config = _config(tmp_path)
    session = open_session(
        config,
        provider="codex",
        provider_session_id="secret-session",
        cwd=tmp_path,
        db_path=db_path,
    )
    checkpoint = checkpoint_session(
        config,
        session_id=session.session_id,
        turn_id="secret-turn",
        structured_state={"state": "client_secret=never-store-this-value"},
        db_path=db_path,
    )
    db = connect(db_path)
    try:
        capsule = db.execute(
            "SELECT capsule_json FROM checkpoints WHERE id=?", (checkpoint["checkpoint_id"],)
        ).fetchone()["capsule_json"]
    finally:
        db.close()
    assert "never-store-this-value" not in capsule
    with pytest.raises(RecordError, match="credential"):
        remember_memory(
            config,
            vault_name="personal",
            project="p",
            summary="api_key=never-store-this-value",
            db_path=db_path,
        )
