from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .semantic import semantic_results
from .services import doctor
from .store import (
    checkpoint_session as save_checkpoint,
)
from .store import (
    latest_session_context,
    search_memories,
)
from .store import (
    publish_handoff as create_handoff,
)
from .store import (
    remember_memory as save_memory,
)
from .sync_v2 import sync_all_events
from .vaults import resolve_vault


def get_session_context(workspace: str) -> dict[str, Any]:
    """Return the latest bounded continuation capsule for a workspace."""
    context = latest_session_context(workspace)
    return {"context": asdict(context) if context else None, "token_budget": 600}


def checkpoint_session(
    session_id: str,
    turn_id: str,
    structured_state: dict[str, Any],
) -> dict[str, Any]:
    """Append a structured checkpoint. Never pass a raw transcript or credentials."""
    return save_checkpoint(
        load_config(),
        session_id=session_id,
        turn_id=turn_id,
        structured_state=structured_state,
    )


def remember_memory(
    summary: str,
    project: str = "general",
    vault: str | None = None,
    details: str = "",
    kind: str = "fact",
    tags: list[str] | None = None,
    workspace: str | None = None,
) -> dict[str, Any]:
    """Append a durable fact, decision, constraint, note, or handoff."""
    config = load_config()
    selected = resolve_vault(config, vault)
    return asdict(
        save_memory(
            config,
            vault_name=selected.name,
            project=project,
            summary=summary,
            details=details,
            kind=kind,
            tags=tags or [],
            workspace_key=workspace,
        )
    )


def search_memory(
    query: str,
    vaults: list[str] | None = None,
    workspace: str | None = None,
    kinds: list[str] | None = None,
    limit: int = 5,
    include_superseded: bool = False,
    semantic: bool = False,
) -> dict[str, Any]:
    """Search the incremental local index without scanning vault files."""
    warnings: list[str] = []
    results = search_memories(
        query,
        limit=limit,
        vaults=vaults,
        workspace_key=workspace,
        kinds=kinds,
        include_superseded=include_superseded,
    )
    if semantic:
        semantic_items, warnings = semantic_results(
            load_config(),
            query,
            limit=limit,
            vaults=vaults,
            workspace_key=workspace,
            kinds=kinds,
            include_superseded=include_superseded,
        )
        if semantic_items:
            combined = {item.id: item for item in [*semantic_items, *results]}
            results = list(combined.values())[:limit]
    return {
        "results": [asdict(item) for item in results],
        "warnings": warnings,
    }


def supersede_memory(
    memory_id: str,
    summary: str,
    project: str,
    vault: str | None = None,
    details: str = "",
    kind: str = "fact",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Append a replacement and mark the old memory superseded in projections."""
    config = load_config()
    selected = resolve_vault(config, vault)
    return asdict(
        save_memory(
            config,
            vault_name=selected.name,
            project=project,
            summary=summary,
            details=details,
            kind=kind,
            tags=tags or [],
            supersedes=[memory_id],
        )
    )


def publish_handoff(
    checkpoint_id: str, team_vault: str, project: str
) -> dict[str, Any]:
    """Explicitly publish a sanitized personal checkpoint into a team vault."""
    return asdict(
        create_handoff(
            load_config(),
            checkpoint_id=checkpoint_id,
            team_vault=team_vault,
            project=project,
        )
    )


def sync_memory(vault: str | None = None) -> dict[str, Any]:
    """Export/import immutable v2 events through configured Git vaults."""
    return {"vaults": sync_all_events(load_config(), vault_name=vault)}


def list_vaults() -> dict[str, Any]:
    config = load_config()
    return {
        "default_vault": config.default_vault,
        "vaults": [
            {"name": item.name, "kind": item.kind}
            for item in sorted(config.vaults.values(), key=lambda value: value.name)
        ],
    }


def doctor_memory() -> dict[str, Any]:
    healthy, messages = doctor(load_config())
    return {"healthy": healthy, "messages": messages}


# Compatibility alias for v1 callers. It writes a v2 event, not Markdown.
def note_memory(
    note_text: str,
    vault: str | None = None,
    project: str = "general",
    tags: list[str] | None = None,
    category: str = "sessions",
    details: str = "",
) -> dict[str, Any]:
    kind = {"decisions": "decision", "sessions": "note", "projects": "fact"}.get(
        category, "note"
    )
    result = remember_memory(note_text, project, vault, details, kind, tags)
    return {
        "ok": True,
        "memory_id": result["id"],
        "vault": result["vault"],
        "project": result["project"],
        "sync": "queued",
        **result,
    }


def create_mcp_server() -> FastMCP:
    server = FastMCP(
        "emu-ai-mem",
        instructions=(
            "Resume with get_session_context. Save only structured checkpoints and durable "
            "memories; never submit raw transcripts or credentials. Team handoffs require "
            "the explicit publish_handoff tool."
        ),
    )
    for tool in (
        get_session_context,
        checkpoint_session,
        remember_memory,
        search_memory,
        supersede_memory,
        publish_handoff,
        sync_memory,
        list_vaults,
        doctor_memory,
        note_memory,
    ):
        server.tool()(tool)
    return server


def run_mcp_server() -> None:
    create_mcp_server().run(transport="stdio")
