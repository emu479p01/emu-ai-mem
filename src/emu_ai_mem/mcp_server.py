from __future__ import annotations

from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP

from .config import load_config
from .gitops import sync_vault
from .index import rebuild_index, search_index
from .services import doctor, find_record, note, remember
from .vaults import resolve_vault


def note_memory(
    note_text: str,
    vault: str | None = None,
    project: str = "general",
    tags: list[str] | None = None,
    category: str = "sessions",
    details: str = "",
) -> dict[str, Any]:
    """Save a user-selected durable note; never pass a raw transcript or credentials."""
    config = load_config()
    selected = resolve_vault(config, vault)
    path, sync_status = note(
        config,
        note_text,
        project=project,
        tags=tags,
        details=details,
        category=category,
        vault_name=selected.name,
    )
    return {
        "ok": True,
        "memory_id": path.stem,
        "vault": selected.name,
        "project": project.strip() or "general",
        "sync": sync_status,
    }


def search_memory(
    query: str,
    vaults: list[str] | None = None,
    limit: int = 5,
    mode: str = "hybrid",
    include_superseded: bool = False,
) -> dict[str, Any]:
    """Search configured local vaults and return provenance for every result."""
    config = load_config()
    if not config.vaults:
        raise ValueError("No vaults configured. Run `emu-mem vault add ...` first.")
    _, index_warnings = rebuild_index(config)
    results, search_warnings = search_index(
        config,
        query,
        mode=mode,
        limit=limit,
        vaults=vaults,
        include_superseded=include_superseded,
    )
    return {
        "results": [asdict(result) for result in results],
        "warnings": index_warnings + search_warnings,
    }


def supersede_memory(
    memory_id: str,
    summary: str,
    project: str,
    vault: str | None = None,
    tags: list[str] | None = None,
    category: str = "sessions",
    details: str = "",
) -> dict[str, Any]:
    """Append a replacement memory without editing or deleting the original."""
    config = load_config()
    found_vault, _ = find_record(config, memory_id, vault)
    selected = vault or found_vault
    path, sync_status = remember(
        config,
        project=project,
        tags=tags or [],
        summary=summary,
        details=details,
        category=category,
        vault_name=selected,
        supersedes=[memory_id],
    )
    return {
        "ok": True,
        "memory_id": path.stem,
        "vault": selected,
        "supersedes": memory_id,
        "sync": sync_status,
    }


def sync_memory(vault: str | None = None) -> dict[str, Any]:
    """Safely fetch, rebase, and push one vault or every configured vault."""
    config = load_config()
    selected = [resolve_vault(config, vault)] if vault else list(config.vaults.values())
    statuses = {item.name: sync_vault(item.name, item.path) for item in selected}
    count, warnings = rebuild_index(config)
    return {"statuses": statuses, "indexed": count, "warnings": warnings}


def list_vaults() -> dict[str, Any]:
    """List available personal and team vaults and identify the explicit default."""
    config = load_config()
    return {
        "default_vault": config.default_vault,
        "vaults": [
            {"name": item.name, "kind": item.kind}
            for item in sorted(config.vaults.values(), key=lambda value: value.name)
        ],
    }


def doctor_memory() -> dict[str, Any]:
    """Check local CLI, Git, vault, index, and pending-push health."""
    healthy, messages = doctor(load_config())
    return {"healthy": healthy, "messages": messages}


def create_mcp_server() -> FastMCP:
    server = FastMCP(
        "emu-ai-mem",
        instructions=(
            "Use search_memory before unfamiliar work. Use note_memory only when the user "
            "explicitly asks to save a durable fact, decision, constraint, or handoff. Never "
            "store raw transcripts or credentials. Never guess a team vault; omit vault only "
            "when the user has deliberately configured a default."
        ),
    )
    server.tool()(note_memory)
    server.tool()(search_memory)
    server.tool()(supersede_memory)
    server.tool()(sync_memory)
    server.tool()(list_vaults)
    server.tool()(doctor_memory)
    return server


def run_mcp_server() -> None:
    create_mcp_server().run(transport="stdio")
