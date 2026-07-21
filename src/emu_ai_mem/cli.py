from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .config import load_config, save_config
from .errors import EmuMemError
from .installers import install_claude_desktop
from .migration_v2 import migrate_v1
from .semantic import index_pending, semantic_results
from .services import doctor, install_generic
from .setup_wizard import (
    SetupReport,
    check_environment,
    configure_setup,
    install_client,
    interactive_setup,
    remove_client,
)
from .store import (
    SessionContext,
    canonical_workspace,
    checkpoint_session,
    latest_session_context,
    open_session,
    publish_handoff,
    remember_memory,
    search_memories,
)
from .sync_v2 import sync_all_events
from .vaults import add_vault, remove_vault, resolve_vault, set_default


def _tags(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _memory_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default="general")
    parser.add_argument("--summary", required=True)
    parser.add_argument("--details", default="")
    parser.add_argument("--kind", default="fact")
    parser.add_argument("--tags", default="")
    parser.add_argument("--workspace")
    parser.add_argument("--vault")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emu-mem", description="Session-first memory for AI agents")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Check and configure the engine and client integrations")
    setup.add_argument("--check", action="store_true")
    setup.add_argument("--client", choices=["codex", "claude-desktop", "claude-code", "gateway"])
    setup.add_argument("--preview", action="store_true")
    setup.add_argument("--remove-client", action="store_true")
    setup.add_argument("--author-id")
    setup.add_argument("--author-name")
    setup.add_argument("--device-id")
    setup.add_argument("--personal-repo")
    setup.add_argument("--personal-name", default="personal")
    setup.add_argument("--team", action="append", default=[])
    setup.add_argument("--smoke-test", action="store_true")

    config_parser = sub.add_parser("config")
    config_sub = config_parser.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")
    identity = config_sub.add_parser("set-identity")
    identity.add_argument("--id", required=True, dest="author_id")
    identity.add_argument("--name", required=True, dest="author_name")
    identity.add_argument("--device-id")

    vault = sub.add_parser("vault")
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

    remember = sub.add_parser("remember")
    _memory_args(remember)
    note = sub.add_parser("note", help="Compatibility shorthand for remember")
    note.add_argument("text")
    note.add_argument("--project", default="general")
    note.add_argument("--details", default="")
    note.add_argument("--tags", default="")
    note.add_argument("--vault")

    supersede = sub.add_parser("supersede")
    supersede.add_argument("memory_id")
    _memory_args(supersede)

    search = sub.add_parser("search")
    search.add_argument("query", nargs="+")
    search.add_argument("--limit", type=int, default=5)
    search.add_argument("--vault", action="append", dest="vaults")
    search.add_argument("--workspace")
    search.add_argument("--kind", action="append", dest="kinds")
    search.add_argument("--include-superseded", action="store_true")
    search.add_argument("--semantic", action="store_true")
    search.add_argument("--json", action="store_true")

    session = sub.add_parser("session")
    session_sub = session.add_subparsers(dest="session_command", required=True)
    latest = session_sub.add_parser("latest")
    latest.add_argument("--workspace")
    latest.add_argument("--cwd", type=Path, default=Path.cwd())
    checkpoint = session_sub.add_parser("checkpoint")
    checkpoint.add_argument("session_id")
    checkpoint.add_argument("--turn-id", required=True)
    checkpoint.add_argument("--state-json")
    open_parser = session_sub.add_parser("open", help=argparse.SUPPRESS)
    open_parser.add_argument("--provider", required=True)
    open_parser.add_argument("--provider-session-id", required=True)
    open_parser.add_argument("--cwd", type=Path, default=Path.cwd())
    open_parser.add_argument("--source", default="startup")

    handoff = sub.add_parser("publish-handoff")
    handoff.add_argument("checkpoint_id")
    handoff.add_argument("--team-vault", required=True)
    handoff.add_argument("--project", required=True)

    sync = sub.add_parser("sync")
    sync.add_argument("--vault")
    sub.add_parser("doctor")

    migrate = sub.add_parser("migrate-v1")
    migrate.add_argument("source", type=Path)
    migrate.add_argument("--vault", required=True)

    install = sub.add_parser("install")
    install_sub = install.add_subparsers(dest="install_command", required=True)
    generic = install_sub.add_parser("generic")
    generic.add_argument("--project", type=Path, default=Path.cwd())
    desktop = install_sub.add_parser("claude-desktop")
    desktop.add_argument("--config", type=Path)

    sub.add_parser("mcp")
    sub.add_parser("semantic-index", help=argparse.SUPPRESS)
    gateway = sub.add_parser("gateway")
    gateway.add_argument("--host", default="127.0.0.1")
    gateway.add_argument("--port", type=int, default=8000)

    hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("event", choices=["session-start", "pre-compact", "stop"])
    hook.add_argument("--client", choices=["codex", "claude"], required=True)
    return parser


def _print_report(report: SetupReport) -> None:
    values = asdict(report)
    print("\n".join([*values["checks"], *values["actions"]]))


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "mcp":
        from .mcp_server import run_mcp_server

        run_mcp_server()
        return 0
    if args.command == "semantic-index":
        count = index_pending(load_config())
        print(f"Indexed {count} semantic memories")
        return 0
    if args.command == "gateway":
        from .gateway import run_gateway

        run_gateway(args.host, args.port)
        return 0
    if args.command == "hook":
        from .hooks import handle_hook

        code, output = handle_hook(args.event, args.client, sys.stdin.read())
        if output:
            print(output)
        return code
    if args.command == "setup":
        configure_requested = any(
            [
                args.author_id,
                args.author_name,
                args.device_id,
                args.personal_repo,
                args.team,
                args.smoke_test,
            ]
        )
        if args.client:
            report = (
                remove_client(args.client, preview=args.preview)
                if args.remove_client
                else install_client(args.client, preview=args.preview)
            )
        elif args.check:
            report = check_environment()
        elif configure_requested:
            report = configure_setup(
                author_id=args.author_id,
                author_name=args.author_name,
                device_id=args.device_id,
                personal_repo=args.personal_repo,
                personal_name=args.personal_name,
                teams=args.team,
                smoke_test=args.smoke_test,
            )
        else:
            report = interactive_setup()
        _print_report(report)
        return 0 if report.healthy or report.actions else 1

    config = load_config()
    if args.command == "config":
        if args.config_command == "show":
            print(json.dumps({"author_id": config.author_id, "author_name": config.author_name, "device_id": config.device_id}, indent=2))
        else:
            config.author_id = args.author_id.strip()
            config.author_name = args.author_name.strip()
            if args.device_id:
                config.device_id = args.device_id.strip()
            save_config(config)
            print("Identity updated")
        return 0
    if args.command == "vault":
        if args.vault_command == "add":
            item = add_vault(config, name=args.name, url=args.url, kind=args.kind, make_default=args.default)
            print(f"Added {item.kind} vault {item.name}: {item.path}")
        elif args.vault_command == "list":
            for name, item in sorted(config.vaults.items()):
                suffix = " (default)" if config.default_vault == name else ""
                print(f"{name}\t{item.kind}\t{item.path}{suffix}")
        elif args.vault_command == "remove":
            path = remove_vault(config, args.name, delete_clone=args.delete_clone)
            print(f"Removed vault configuration; clone: {path}")
        else:
            set_default(config, args.name)
            print(f"Default vault: {args.name}")
        return 0
    if args.command in {"remember", "note", "supersede"}:
        selected = resolve_vault(config, args.vault)
        summary = args.text if args.command == "note" else args.summary
        result = remember_memory(
            config,
            vault_name=selected.name,
            project=args.project,
            summary=summary,
            details=args.details,
            kind="note" if args.command == "note" else args.kind,
            tags=_tags(args.tags),
            workspace_key=getattr(args, "workspace", None),
            supersedes=[args.memory_id] if args.command == "supersede" else [],
        )
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        return 0
    if args.command == "search":
        query = " ".join(args.query)
        results = search_memories(
            query,
            limit=args.limit,
            vaults=args.vaults,
            workspace_key=args.workspace,
            kinds=args.kinds,
            include_superseded=args.include_superseded,
        )
        if args.semantic:
            semantic_items, warnings = semantic_results(
                config,
                query,
                limit=args.limit,
                vaults=args.vaults,
                workspace_key=args.workspace,
                kinds=args.kinds,
                include_superseded=args.include_superseded,
            )
            if semantic_items:
                by_id = {item.id: item for item in [*semantic_items, *results]}
                results = list(by_id.values())[: args.limit]
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
        if args.json:
            print(json.dumps([asdict(item) for item in results], ensure_ascii=False, indent=2))
        else:
            for search_result in results:
                print(
                    f"[{search_result.vault}] {search_result.id} {search_result.kind}\n"
                    f"  {search_result.summary}\n  {search_result.provenance}"
                )
        return 0
    if args.command == "session":
        context: SessionContext | None
        if args.session_command == "open":
            context = open_session(
                config,
                provider=args.provider,
                provider_session_id=args.provider_session_id,
                cwd=args.cwd,
                start_source=args.source,
            )
        elif args.session_command == "latest":
            workspace = args.workspace or canonical_workspace(args.cwd)[0]
            context = latest_session_context(workspace)
        else:
            raw = args.state_json if args.state_json is not None else sys.stdin.read()
            checkpoint_result = checkpoint_session(
                config,
                session_id=args.session_id,
                turn_id=args.turn_id,
                structured_state=json.loads(raw or "{}"),
            )
            print(json.dumps(checkpoint_result, ensure_ascii=False, indent=2))
            return 0
        print(json.dumps(asdict(context) if context else None, ensure_ascii=False, indent=2))
        return 0
    if args.command == "publish-handoff":
        handoff_result = publish_handoff(
            config,
            checkpoint_id=args.checkpoint_id,
            team_vault=args.team_vault,
            project=args.project,
        )
        print(json.dumps(asdict(handoff_result), ensure_ascii=False, indent=2))
        return 0
    if args.command == "sync":
        print(json.dumps(sync_all_events(config, vault_name=args.vault), ensure_ascii=False, indent=2))
        return 0
    if args.command == "doctor":
        healthy, messages = doctor(config)
        print("\n".join(messages))
        return 0 if healthy else 1
    if args.command == "migrate-v1":
        count, warnings = migrate_v1(config, args.source, vault_name=args.vault)
        print(f"Imported {count} v1 memories")
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        return 0 if not warnings else 1
    if args.command == "install":
        if args.install_command == "generic":
            print(f"Wrote {install_generic(args.project)}")
        else:
            print(f"Configured Claude Desktop local MCP: {install_claude_desktop(args.config)}")
        return 0
    return 2


def main() -> None:
    try:
        raise SystemExit(dispatch(build_parser().parse_args()))
    except (EmuMemError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
