from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import load_config, save_config
from .installers import install_claude_desktop, remove_claude_desktop
from .paths import config_path, data_dir, state_path
from .store import remember_memory, search_memories
from .sync_v2 import sync_all_events
from .vaults import add_vault


@dataclass(slots=True)
class SetupReport:
    healthy: bool
    checks: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return "not available"


def check_environment() -> SetupReport:
    config = load_config(create=False)
    git = shutil.which("git")
    github_cli = shutil.which("gh")
    python_ok = sys.version_info[:2] in {(3, 11), (3, 12)}
    config_target = config_path()
    data_target = data_dir()

    def writable_ancestor(path: Path) -> bool:
        candidate = path
        while not candidate.exists() and candidate != candidate.parent:
            candidate = candidate.parent
        return os.access(candidate, os.W_OK)

    filesystem_ok = writable_ancestor(config_target) and writable_ancestor(data_target)
    github_status = _version([github_cli, "auth", "status"]) if github_cli else "not available"
    report = SetupReport(
        healthy=bool(git and python_ok and filesystem_ok and config.vaults)
    )
    report.checks.extend(
        [
            f"os: {sys.platform}",
            f"python: {_version([sys.executable, '--version'])}",
            f"git: {_version([git, '--version']) if git else 'not available'}",
            f"github auth: {github_status}",
            f"PATH emu-mem: {shutil.which('emu-mem') or 'not available'}",
            f"config: {config_path()}",
            f"data: {data_dir()}",
            f"database: {state_path()}",
            f"filesystem permissions: {'writable' if filesystem_ok else 'not writable'}",
            f"vaults: {len(config.vaults)}",
            f"personal vault: {'yes' if any(v.kind == 'personal' for v in config.vaults.values()) else 'no'}",
        ]
    )
    return report


def install_client(client: str, *, preview: bool = False) -> SetupReport:
    report = check_environment()
    if client == "claude-desktop":
        if preview:
            report.actions.append("Would merge the local MCP server into Claude Desktop config")
        else:
            target = install_claude_desktop()
            report.actions.append(f"Installed Claude Desktop MCP entry: {target}")
    elif client == "codex":
        commands = [
            ["codex", "plugin", "marketplace", "add", "emu479p01/emu-ai-mem"],
            ["codex", "plugin", "add", "emu-ai-mem@emu-ai-mem"],
        ]
        if preview:
            report.actions.extend("Would run: " + " ".join(item) for item in commands)
        else:
            for command in commands:
                subprocess.run(command, check=True)
            report.actions.append("Installed Codex plugin; review and trust hooks in Codex")
    elif client == "claude-code":
        report.actions.append(
            "In Claude Code run: /plugin marketplace add emu479p01/emu-ai-mem, "
            "then /plugin install emu-ai-mem@emu-ai-mem"
        )
    elif client == "gateway":
        report.actions.append(
            "Install emu-ai-mem[gateway], configure the documented EMU_MEM_GATEWAY_* "
            "secrets, then run `emu-mem gateway` behind HTTPS"
        )
    else:
        raise ValueError(f"Unsupported client: {client}")
    return report


def remove_client(client: str, *, preview: bool = False) -> SetupReport:
    report = check_environment()
    if client == "claude-desktop":
        if preview:
            report.actions.append("Would remove only emu-ai-mem from Claude Desktop MCP config")
        else:
            report.actions.append(f"Removed Claude Desktop MCP entry: {remove_claude_desktop()}")
    elif client == "codex":
        command = ["codex", "plugin", "remove", "emu-ai-mem@emu-ai-mem"]
        if preview:
            report.actions.append("Would run: " + " ".join(command))
        else:
            subprocess.run(command, check=True)
            report.actions.append("Removed Codex plugin; vaults and local database were preserved")
    elif client == "claude-code":
        report.actions.append("In Claude Code run: /plugin uninstall emu-ai-mem@emu-ai-mem")
    elif client == "gateway":
        report.actions.append(
            "Disconnect the custom app/connector in each client. Do not delete the gateway volume "
            "until OAuth mappings and backups have been reviewed."
        )
    else:
        raise ValueError(f"Unsupported client: {client}")
    return report


def configure_setup(
    *,
    author_id: str | None = None,
    author_name: str | None = None,
    device_id: str | None = None,
    personal_repo: str | None = None,
    personal_name: str = "personal",
    teams: list[str] | None = None,
    smoke_test: bool = False,
) -> SetupReport:
    config = load_config()
    if author_id:
        config.author_id = author_id.strip()
    if author_name:
        config.author_name = author_name.strip()
    if device_id:
        config.device_id = device_id.strip()
    save_config(config)
    actions = ["Identity/config saved atomically"]
    if personal_repo and personal_name not in config.vaults:
        add_vault(
            config,
            name=personal_name,
            url=personal_repo,
            kind="personal",
            make_default=True,
        )
        actions.append(f"Connected personal vault: {personal_name}")
    for specification in teams or []:
        if "=" not in specification:
            raise ValueError("--team must use NAME=GIT_URL")
        name, url = specification.split("=", 1)
        if name not in config.vaults:
            add_vault(config, name=name, url=url, kind="team")
            actions.append(f"Connected team vault: {name}")
    if smoke_test:
        personal = next(
            (vault for vault in config.vaults.values() if vault.kind == "personal"), None
        )
        if not personal:
            raise ValueError("--smoke-test requires a personal vault")
        result = remember_memory(
            config,
            vault_name=personal.name,
            project="onboarding",
            summary="emu-ai-mem v2 setup smoke test",
            kind="diagnostic",
            tags=["setup", "smoke-test"],
        )
        sync_all_events(config, vault_name=personal.name)
        found = search_memories("setup smoke test", vaults=[personal.name])
        if not any(item.id == result.id for item in found):
            raise RuntimeError("Setup smoke test could not read its committed memory")
        actions.append(f"Smoke test passed with provenance {result.provenance}:{result.id}")
    report = check_environment()
    report.actions.extend(actions)
    return report


def interactive_setup() -> SetupReport:
    if not sys.stdin.isatty():
        report = check_environment()
        report.actions.append(
            "Non-interactive input detected. Use --author-id/--author-name/--device-id, "
            "--personal-repo, --team NAME=URL, and optional --smoke-test."
        )
        return report
    config = load_config()
    author_id = input(f"Author ID [{config.author_id}]: ").strip() or config.author_id
    author_name = input(f"Author name [{config.author_name}]: ").strip() or config.author_name
    device_id = input(f"Unique device ID [{config.device_id}]: ").strip() or config.device_id
    personal_repo = None
    if not any(vault.kind == "personal" for vault in config.vaults.values()):
        personal_repo = input("Private personal Git repository URL (blank to skip): ").strip() or None
    report = configure_setup(
        author_id=author_id,
        author_name=author_name,
        device_id=device_id,
        personal_repo=personal_repo,
    )
    report.actions.append(
        "Run `emu-mem setup --smoke-test` after connecting a personal vault, then install clients."
    )
    return report
