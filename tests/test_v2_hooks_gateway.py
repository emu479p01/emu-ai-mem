from __future__ import annotations

import asyncio
import json
from pathlib import Path

from cryptography.fernet import Fernet
from mcp.shared.auth import OAuthClientInformationFull

from emu_ai_mem.config import VaultConfig, load_config, save_config
from emu_ai_mem.gateway_auth import GatewayOAuthProvider
from emu_ai_mem.hooks import handle_hook
from emu_ai_mem.store import open_session


def test_stop_hook_requests_one_checkpoint_retry(
    app_home: Path, tmp_path: Path
) -> None:
    vault_path = tmp_path / "personal"
    vault_path.mkdir()
    config = load_config()
    config.default_vault = "personal"
    config.vaults["personal"] = VaultConfig("personal", "unused", vault_path, "personal")
    save_config(config)
    open_session(
        config,
        provider="codex",
        provider_session_id="provider-session",
        cwd=tmp_path,
    )
    payload = json.dumps(
        {"session_id": "provider-session", "turn_id": "turn-1", "cwd": str(tmp_path)}
    )
    first = handle_hook("stop", "codex", payload)
    second = handle_hook("stop", "codex", payload)
    assert "checkpoint_session" in first[1]
    assert second == (0, "")


def test_claude_hook_outputs_follow_event_contract(app_home: Path, tmp_path: Path) -> None:
    vault_path = tmp_path / "personal"
    vault_path.mkdir()
    config = load_config()
    config.default_vault = "personal"
    config.vaults["personal"] = VaultConfig("personal", "unused", vault_path, "personal")
    save_config(config)
    open_session(
        config,
        provider="claude",
        provider_session_id="claude-session",
        cwd=tmp_path,
    )
    payload = json.dumps(
        {"session_id": "claude-session", "turn_id": "turn-1", "cwd": str(tmp_path)}
    )
    compact = json.loads(handle_hook("pre-compact", "claude", payload)[1])
    assert compact["decision"] == "block"
    assert "checkpoint_session" in compact["reason"]
    stop = json.loads(handle_hook("stop", "claude", payload)[1])
    assert stop["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "checkpoint_session" in stop["hookSpecificOutput"]["additionalContext"]


def test_plugins_do_not_search_every_prompt() -> None:
    root = Path(__file__).parents[1]
    for path in (
        root / "plugins" / "emu-ai-mem" / "hooks" / "hooks.json",
        root / "claude-plugins" / "emu-ai-mem" / "hooks" / "hooks.json",
    ):
        hooks = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        assert "UserPromptSubmit" not in hooks
        assert {"SessionStart", "PreCompact", "Stop"} <= set(hooks)


def test_gateway_tokens_rotate_and_are_subject_bound(tmp_path: Path) -> None:
    async def exercise() -> None:
        provider = GatewayOAuthProvider(
            db_path=tmp_path / "auth.db",
            base_url="https://memory.example.com",
            github_client_id="client",
            github_client_secret="secret",
            encryption_key=Fernet.generate_key().decode(),
        )
        client = OAuthClientInformationFull(
            client_id="mcp-client",
            redirect_uris=["https://chat.example.com/callback"],
        )
        await provider.register_client(client)
        issued = provider._issue_tokens(  # noqa: SLF001 - verifies security storage behavior
            client_id="mcp-client",
            subject="alice",
            scopes=["memory:read", "memory:write"],
            resource="https://memory.example.com/mcp",
        )
        access = await provider.load_access_token(issued.access_token)
        assert access and access.subject == "alice"
        assert access.resource == "https://memory.example.com/mcp"
        refresh = await provider.load_refresh_token(client, str(issued.refresh_token))
        assert refresh
        rotated = await provider.exchange_refresh_token(client, refresh, ["memory:read"])
        assert await provider.load_access_token(issued.access_token) is None
        assert await provider.load_access_token(rotated.access_token)
        await provider.revoke_token(
            await provider.load_access_token(rotated.access_token)  # type: ignore[arg-type]
        )
        assert await provider.load_access_token(rotated.access_token) is None

    asyncio.run(exercise())
