from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .errors import ConfigurationError

SERVER_NAME = "emu-ai-mem"


def claude_desktop_config_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ConfigurationError("APPDATA is not set; pass --config explicitly")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / (
            "claude_desktop_config.json"
        )
    raise ConfigurationError(
        "Claude Desktop local MCP installation is supported on Windows and macOS"
    )


def _cli_invocation(executable: Path | None = None) -> tuple[str, list[str]]:
    if executable is not None:
        return str(executable.resolve()), ["mcp"]
    installed = shutil.which("emu-mem")
    if installed:
        return str(Path(installed).resolve()), ["mcp"]
    return str(Path(sys.executable).resolve()), ["-m", "emu_ai_mem", "mcp"]


def install_claude_desktop(
    config_file: Path | None = None, *, executable: Path | None = None
) -> Path:
    """Install a user-wide local stdio MCP entry while preserving other Claude settings."""
    target = (config_file or claude_desktop_config_path()).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if target.exists():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"Invalid Claude Desktop config {target}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ConfigurationError(f"Claude Desktop config must contain a JSON object: {target}")
        payload = loaded
        backup = target.with_suffix(target.suffix + ".bak")
        shutil.copy2(target, backup)

    servers = payload.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ConfigurationError("Claude Desktop config mcpServers must be a JSON object")
    command, args = _cli_invocation(executable)
    servers[SERVER_NAME] = {"command": command, "args": args}

    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, target)
    return target


def remove_claude_desktop(config_file: Path | None = None) -> Path:
    """Remove only emu-ai-mem's MCP entry, preserving all other client settings."""
    target = (config_file or claude_desktop_config_path()).expanduser().resolve()
    if not target.exists():
        return target
    loaded = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ConfigurationError(f"Claude Desktop config must contain an object: {target}")
    backup = target.with_suffix(target.suffix + ".bak")
    shutil.copy2(target, backup)
    servers = loaded.get("mcpServers")
    if isinstance(servers, dict):
        servers.pop(SERVER_NAME, None)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(loaded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, target)
    return target
