from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .config import load_config, save_config
from .errors import EmuMemError
from .gitops import sync_vault
from .index import rebuild_index, search_index
from .installers import install_claude_desktop
from .services import doctor, find_record, hook, install_generic, migrate_legacy, note, remember
from .vaults import add_vault, remove_vault, resolve_vault, set_default


def _tags(value: str) -> list[str]:
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def _add_memory_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--tags", default="")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--details", default="")
    parser.add_argument(
        "--category", choices=["projects", "sessions", "decisions"], default="sessions"
    )
    parser.add_argument("--vault")
    parser.add_argument("--no-sync", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emu-mem", description="Git-backed memory for AI agent teams"
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    config_parser = sub.add_parser("config", help="Inspect or update local identity")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")
    identity = config_sub.add_parser("set-identity")
    identity.add_argument("--id", required=True, dest="author_id")
    identity.add_argument("--name", required=True, dest="author_name")
    identity.add_argument("--device-id")

    vault = sub.add_parser("vault", help="Manage memory repositories")
    vault_sub = vault.add_subparsers(dest="vault_command", required=True)
    add = vault_sub.add_parser("add")
    add.add_argument("name")
    add.add_argument("url")
    add.add_argument("--kind", choices=["personal", "team"], required=True)
    add.add_argument("--default", action="store_true")
    vault_sub.add_parser("list")
    remove = vault_sub.add_parser("remove")
    remove.add_argument("name")
    remove.add_argument("--delete-clone", action="store_true")
    default = vault_sub.add_parser("set-default")
    default.add_argument("name")

    remember_parser = sub.add_parser("remember", help="Create an append-only memory")
    _add_memory_args(remember_parser)
    note_parser = sub.add_parser(
        "note", help="Save an explicit note without depending on the current folder"
    )
    note_parser.add_argument("text")
    note_parser.add_argument("--project", default="general")
    note_parser.add_argument("--tags", default="")
    note_parser.add_argument("--details", default="")
    note_parser.add_argument(
        "--category", choices=["projects", "sessions", "decisions"], default="sessions"
    )
    note_parser.add_argument("--vault")
    note_parser.add_argument("--no-sync", action="store_true")
    supersede = sub.add_parser("supersede", help="Create a replacement for an existing memory")
    supersede.add_argument("memory_id")
    _add_memory_args(supersede)

    search = sub.add_parser("search")
    search.add_argument("query", nargs="+")
    search.add_argument("--mode", choices=["fts", "vec", "hybrid"], default="hybrid")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--vault", action="append", dest="vaults")
    search.add_argument("--include-superseded", action="store_true")
    search.add_argument("--json", action="store_true")

    sync = sub.add_parser("sync")
    sync.add_argument("--vault")
    sub.add_parser("reindex")
    sub.add_parser("doctor")

    migrate = sub.add_parser("migrate")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("--vault")
    migrate.add_argument("--no-sync", action="store_true")

    install = sub.add_parser("install")
    install_sub = install.add_subparsers(dest="install_command", required=True)
    generic = install_sub.add_parser("generic")
    generic.add_argument("--project", type=Path, default=Path.cwd())
    claude_desktop = install_sub.add_parser(
        "claude-desktop", help="Install the user-wide local MCP server for Claude Desktop"
    )
    claude_desktop.add_argument("--config", type=Path)

    sub.add_parser("mcp", help="Run the local Model Context Protocol server over stdio")

    hook_parser = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook_parser.add_argument("event", choices=["session-start", "prompt", "pre-compact", "stop"])
    hook_parser.add_argument("--client", choices=["plain", "codex", "claude"], default="plain")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "hook":
        code, output = hook(args.event, sys.stdin.read())
        if output and args.client == "codex":
            print(json.dumps({"continue": True, "systemMessage": output}))
        elif output and args.client == "claude" and args.event in {"session-start", "prompt"}:
            event_name = "SessionStart" if args.event == "session-start" else "UserPromptSubmit"
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": event_name,
                            "additionalContext": output,
                        }
                    }
                )
            )
        elif output and args.client == "plain":
            print(output)
        return code

    if args.command == "mcp":
        from .mcp_server import run_mcp_server

        run_mcp_server()
        return 0

    if args.command == "install" and args.install_command == "claude-desktop":
        target = install_claude_desktop(args.config)
        print(f"Configured Claude Desktop local MCP: {target}")
        print("Restart Claude Desktop, enable emu-ai-mem, and allow write tools when prompted.")
        return 0

    config = load_config()
    if args.command == "config":
        if args.config_command == "show":
            print(f"author_id: {config.author_id}")
            print(f"author_name: {config.author_name}")
            print(f"device_id: {config.device_id}")
        else:
            config.author_id = args.author_id.strip()
            config.author_name = args.author_name.strip()
            if args.device_id:
                config.device_id = args.device_id.strip()
            if not config.author_id or not config.author_name or not config.device_id:
                raise EmuMemError("Identity values cannot be empty")
            save_config(config)
            print("Identity updated")
        return 0

    if args.command == "vault":
        if args.vault_command == "add":
            vault = add_vault(
                config, name=args.name, url=args.url, kind=args.kind, make_default=args.default
            )
            print(f"Added {vault.kind} vault {vault.name}: {vault.path}")
        elif args.vault_command == "list":
            for name, vault in sorted(config.vaults.items()):
                default = " (default)" if config.default_vault == name else ""
                print(f"{name}\t{vault.kind}\t{vault.path}{default}")
        elif args.vault_command == "remove":
            path = remove_vault(config, args.name, delete_clone=args.delete_clone)
            suffix = "deleted" if args.delete_clone else "preserved"
            print(f"Removed vault configuration; clone {suffix}: {path}")
        else:
            set_default(config, args.name)
            print(f"Default vault: {args.name}")
        return 0

    if args.command == "note":
        path, status = note(
            config,
            args.text,
            project=args.project,
            tags=_tags(args.tags),
            details=args.details,
            category=args.category,
            vault_name=args.vault,
            auto_sync=not args.no_sync,
        )
        print(f"Wrote {path}\nSync: {status}")
        return 0

    if args.command in {"remember", "supersede"}:
        supersedes: list[str] = []
        vault_name = args.vault
        if args.command == "supersede":
            found_vault, _ = find_record(config, args.memory_id, args.vault)
            vault_name = vault_name or found_vault
            supersedes = [args.memory_id]
        path, status = remember(
            config,
            project=args.project,
            tags=_tags(args.tags),
            summary=args.summary,
            details=args.details,
            category=args.category,
            vault_name=vault_name,
            supersedes=supersedes,
            auto_sync=not args.no_sync,
        )
        print(f"Wrote {path}\nSync: {status}")
        return 0

    if args.command == "search":
        if not config.vaults:
            raise EmuMemError("No vaults configured. Run `emu-mem vault add ...` first.")
        rebuild_index(config)
        results, warnings = search_index(
            config,
            " ".join(args.query),
            mode=args.mode,
            limit=args.limit,
            vaults=args.vaults,
            include_superseded=args.include_superseded,
        )
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        if args.json:
            print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))
        else:
            for result in results:
                print(
                    f"[{result.vault}] {result.id} ({result.score:.4f})\n  {result.summary}\n  {result.path}"
                )
        return 0

    if args.command == "sync":
        vaults = [resolve_vault(config, args.vault)] if args.vault else list(config.vaults.values())
        for vault in vaults:
            print(f"{vault.name}: {sync_vault(vault.name, vault.path)}")
        rebuild_index(config)
        return 0

    if args.command == "reindex":
        count, warnings = rebuild_index(config, full=True)
        print(f"Indexed {count} memories")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0

    if args.command == "doctor":
        healthy, messages = doctor(config)
        print("\n".join(messages))
        return 0 if healthy else 1

    if args.command == "migrate":
        count, warnings = migrate_legacy(
            config, args.source, vault_name=args.vault, auto_sync=not args.no_sync
        )
        print(f"Imported {count} memories")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0 if not warnings else 1

    if args.command == "install" and args.install_command == "generic":
        print(f"Wrote {install_generic(args.project)}")
        return 0
    return 2


def main() -> None:
    try:
        raise SystemExit(dispatch(build_parser().parse_args()))
    except EmuMemError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
