from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import asdict
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl, TypeAdapter
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse

from .gateway_auth import GatewayOAuthProvider
from .gateway_backend import GitHubGatewayBackend
from .paths import gateway_dir
from .semantic import semantic_results
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


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the remote gateway")
    return value


def create_gateway_server(host: str = "127.0.0.1", port: int = 8000) -> FastMCP:
    base_url = _required("EMU_MEM_GATEWAY_BASE_URL").rstrip("/")
    if not base_url.startswith("https://") and not base_url.startswith("http://localhost"):
        raise RuntimeError("EMU_MEM_GATEWAY_BASE_URL must use HTTPS outside localhost")
    allowlist = {
        item.strip()
        for item in os.environ.get("EMU_MEM_GATEWAY_GITHUB_ALLOWLIST", "").split(",")
        if item.strip()
    }
    root = gateway_dir()
    provider = GatewayOAuthProvider(
        db_path=root / "gateway-auth.sqlite3",
        base_url=base_url,
        github_client_id=_required("EMU_MEM_GATEWAY_GITHUB_CLIENT_ID"),
        github_client_secret=_required("EMU_MEM_GATEWAY_GITHUB_CLIENT_SECRET"),
        encryption_key=_required("EMU_MEM_GATEWAY_ENCRYPTION_KEY"),
        github_allowlist=allowlist,
    )
    backend = GitHubGatewayBackend(provider, root)
    url_adapter = TypeAdapter(AnyHttpUrl)
    auth = AuthSettings(
        issuer_url=url_adapter.validate_python(base_url),
        resource_server_url=url_adapter.validate_python(f"{base_url}/mcp"),
        required_scopes=["memory:read"],
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["memory:read", "memory:write"],
            default_scopes=["memory:read", "memory:write"],
        ),
        revocation_options=RevocationOptions(enabled=True),
    )
    server = FastMCP(
        "emu-ai-mem-gateway",
        instructions=(
            "Remote access to GitHub-backed emu-ai-mem vaults. Never submit raw transcripts "
            "or credentials. Writes create immutable v2 events in an explicitly configured vault."
        ),
        auth_server_provider=provider,
        auth=auth,
        host=host,
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
    )

    def subject(*, write: bool = False) -> str:
        token = get_access_token()
        if not token or not token.subject:
            raise ValueError("Authenticated GitHub subject is required")
        if write and "memory:write" not in token.scopes:
            raise ValueError("This action requires the memory:write scope")
        return token.subject

    @server.tool()
    async def configure_github_vault(name: str, repository: str, kind: str) -> dict[str, Any]:
        """Allow one private GitHub repository as a personal or team vault."""
        owner = subject(write=True)
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,62}", name):
            raise ValueError("Vault name must use lowercase letters, numbers, dot, dash, or underscore")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("repository must use OWNER/REPOSITORY format")
        repo = await backend.verify_repository(owner, repository)
        if not repo["private"]:
            raise ValueError("Gateway vault repositories must be private")
        if not repo["can_push"]:
            raise ValueError("GitHub account does not have write access to this repository")
        provider.configure_vault(owner, name, repo["repository"], kind)
        await backend.refresh(owner, name)
        return {"name": name, "repository": repo["repository"], "kind": kind}

    @server.tool()
    async def list_vaults() -> dict[str, Any]:
        owner = subject()
        vaults = provider.vaults(owner)
        default = next((item["name"] for item in vaults if item["default_vault"]), None)
        return {"default_vault": default, "vaults": vaults}

    @server.tool()
    async def search_memory(
        query: str,
        vaults: list[str] | None = None,
        workspace: str | None = None,
        kinds: list[str] | None = None,
        limit: int = 5,
        include_superseded: bool = False,
        semantic: bool = False,
    ) -> dict[str, Any]:
        owner = subject()
        refreshed = await backend.refresh(owner)
        results = search_memories(
            query,
            vaults=vaults,
            workspace_key=workspace,
            kinds=kinds,
            limit=limit,
            include_superseded=include_superseded,
            db_path=backend.tenant_db(owner),
        )
        warnings = list(refreshed["warnings"])
        if semantic:
            semantic_items, semantic_warnings = semantic_results(
                backend.config(owner),
                query,
                vaults=vaults,
                workspace_key=workspace,
                kinds=kinds,
                limit=limit,
                include_superseded=include_superseded,
                db_path=backend.tenant_db(owner),
            )
            warnings.extend(semantic_warnings)
            if semantic_items:
                combined = {item.id: item for item in [*semantic_items, *results]}
                results = list(combined.values())[:limit]
        return {"results": [asdict(item) for item in results], "warnings": warnings}

    @server.tool()
    async def remember_memory(
        summary: str,
        project: str = "general",
        vault: str | None = None,
        details: str = "",
        kind: str = "fact",
        tags: list[str] | None = None,
        workspace: str | None = None,
    ) -> dict[str, Any]:
        owner = subject(write=True)
        config = backend.config(owner)
        selected = vault or config.default_vault
        if not selected:
            raise ValueError("Configure an explicit gateway vault first")
        result = save_memory(
            config,
            vault_name=selected,
            project=project,
            summary=summary,
            details=details,
            kind=kind,
            tags=tags or [],
            workspace_key=workspace,
            db_path=backend.tenant_db(owner),
        )
        sync = await backend.flush(owner, selected)
        return {**asdict(result), "sync": sync}

    @server.tool()
    async def supersede_memory(
        memory_id: str,
        summary: str,
        project: str,
        vault: str,
        details: str = "",
        kind: str = "fact",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        owner = subject(write=True)
        config = backend.config(owner)
        result = save_memory(
            config,
            vault_name=vault,
            project=project,
            summary=summary,
            details=details,
            kind=kind,
            tags=tags or [],
            supersedes=[memory_id],
            db_path=backend.tenant_db(owner),
        )
        sync = await backend.flush(owner, vault)
        return {**asdict(result), "sync": sync}

    @server.tool()
    async def get_session_context(workspace: str) -> dict[str, Any]:
        owner = subject()
        await backend.refresh(owner)
        context = latest_session_context(workspace, db_path=backend.tenant_db(owner))
        return {"context": asdict(context) if context else None, "token_budget": 600}

    @server.tool()
    async def checkpoint_session(
        session_id: str, turn_id: str, structured_state: dict[str, Any]
    ) -> dict[str, Any]:
        owner = subject(write=True)
        config = backend.config(owner)
        result = save_checkpoint(
            config,
            session_id=session_id,
            turn_id=turn_id,
            structured_state=structured_state,
            db_path=backend.tenant_db(owner),
        )
        personal = next(item.name for item in config.vaults.values() if item.kind == "personal")
        result["sync"] = await backend.flush(owner, personal)
        return result

    @server.tool()
    async def publish_handoff(
        checkpoint_id: str, team_vault: str, project: str
    ) -> dict[str, Any]:
        owner = subject(write=True)
        result = create_handoff(
            backend.config(owner),
            checkpoint_id=checkpoint_id,
            team_vault=team_vault,
            project=project,
            db_path=backend.tenant_db(owner),
        )
        sync = await backend.flush(owner, team_vault)
        return {**asdict(result), "sync": sync}

    @server.tool()
    async def sync_memory(vault: str | None = None) -> dict[str, Any]:
        owner = subject(write=True)
        refreshed = await backend.refresh(owner, vault)
        exported = {}
        for item in provider.vaults(owner):
            if vault is None or item["name"] == vault:
                exported[item["name"]] = await backend.flush(owner, item["name"])
        return {"refresh": refreshed, "export": exported}

    @server.tool()
    async def doctor_memory() -> dict[str, Any]:
        owner = subject()
        vaults = provider.vaults(owner)
        return {
            "healthy": bool(vaults),
            "subject": owner,
            "vault_count": len(vaults),
            "database": "tenant-isolated",
        }

    @server.custom_route("/health", methods=["GET"])  # type: ignore[untyped-decorator]
    async def health(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "service": "emu-ai-mem-gateway"})

    @server.custom_route("/oauth/github/callback", methods=["GET"])  # type: ignore[untyped-decorator]
    async def github_callback(request: Request) -> RedirectResponse | JSONResponse:
        code = request.query_params.get("code")
        state = request.query_params.get("state")
        if not code or not state:
            return JSONResponse({"error": "code and state are required"}, status_code=400)
        try:
            redirect = await provider.complete_github_authorization(code, state)
            return RedirectResponse(redirect, status_code=302)
        except Exception:
            return JSONResponse({"error": "GitHub authorization failed"}, status_code=400)

    @server.custom_route("/webhooks/github", methods=["POST"])  # type: ignore[untyped-decorator]
    async def github_webhook(request: Request) -> JSONResponse:
        secret = os.environ.get("EMU_MEM_GATEWAY_GITHUB_WEBHOOK_SECRET", "")
        if not secret:
            return JSONResponse({"error": "webhooks disabled"}, status_code=404)
        body = await request.body()
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        received = request.headers.get("x-hub-signature-256", "")
        if not hmac.compare_digest(expected, received):
            return JSONResponse({"error": "invalid signature"}, status_code=401)
        payload = json.loads(body)
        repository = str(payload.get("repository", {}).get("full_name", ""))
        refreshed = []
        for owner in provider.subjects_for_repository(repository):
            refreshed.append(await backend.refresh(owner))
        return JSONResponse({"refreshed": refreshed})

    return server


def run_gateway(host: str = "127.0.0.1", port: int = 8000) -> None:
    create_gateway_server(host, port).run(transport="streamable-http")
