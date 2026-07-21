from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from emu_ai_mem.config import load_config
from emu_ai_mem.errors import ConfigurationError
from emu_ai_mem.mcp_server import note_memory
from emu_ai_mem.records import MemoryRecord
from emu_ai_mem.services import note
from emu_ai_mem.store import connect
from emu_ai_mem.vaults import add_vault


def test_note_memory_never_guesses_a_vault(app_home: Path) -> None:
    with pytest.raises(ConfigurationError, match="No default vault"):
        note_memory("Do not guess where this belongs")


def test_note_uses_default_vault_without_current_folder(
    app_home: Path, bare_remote: Path, monkeypatch
) -> None:
    config = load_config()
    add_vault(config, name="personal", url=str(bare_remote), kind="personal", make_default=True)
    unrelated = app_home.parent / "unrelated-chat-folder"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)

    path, status = note(config, "Keep this durable fact", auto_sync=False)

    record = MemoryRecord.from_path(path)
    assert path.is_relative_to(config.vaults["personal"].path)
    assert not path.is_relative_to(unrelated)
    assert record.project == "general"
    assert record.category == "sessions"
    assert status == "committed locally"


def test_note_memory_returns_provenance(app_home: Path, bare_remote: Path) -> None:
    config = load_config()
    add_vault(config, name="team", url=str(bare_remote), kind="team", make_default=True)

    result = note_memory(
        "Use append-only decisions",
        project="engine",
        tags=["decision"],
        category="decisions",
    )

    assert result["ok"] is True
    assert result["vault"] == "team"
    assert result["project"] == "engine"
    assert result["sync"] == "queued"
    memory_id = str(result["memory_id"])
    db = connect()
    try:
        assert db.execute("SELECT 1 FROM memories WHERE id=?", (memory_id,)).fetchone()
        assert db.execute("SELECT 1 FROM outbox").fetchone()
    finally:
        db.close()


def test_stdio_mcp_lists_folder_independent_tools(app_home: Path) -> None:
    async def exercise() -> None:
        environment = dict(os.environ)
        environment["EMU_MEM_HOME"] = str(app_home)
        environment["EMU_MEM_DISABLE_EMBEDDINGS"] = "1"
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "emu_ai_mem", "mcp"],
            env=environment,
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.list_tools()
                names = {tool.name for tool in response.tools}
                assert names == {
                    "checkpoint_session",
                    "doctor_memory",
                    "get_session_context",
                    "list_vaults",
                    "note_memory",
                    "publish_handoff",
                    "remember_memory",
                    "search_memory",
                    "supersede_memory",
                    "sync_memory",
                }
                result = await session.call_tool("list_vaults", {})
                assert not result.isError

    asyncio.run(exercise())
