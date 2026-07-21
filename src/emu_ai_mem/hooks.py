from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .store import (
    checkpoint_for_turn,
    claim_hook_retry,
    open_session,
    provider_session,
)


def _background_sync() -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "emu_ai_mem", "sync"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except OSError:
        pass


def _client_output(client: str, event: str, message: str) -> str:
    if not message:
        return ""
    if client == "claude" and event == "session-start":
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                }
            }
        )
    if client == "claude" and event == "stop":
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "Stop",
                    "additionalContext": message,
                }
            }
        )
    if client == "claude" and event == "pre-compact":
        return json.dumps({"decision": "block", "reason": message})
    return json.dumps({"continue": True, "systemMessage": message})


def _checkpoint_instruction(session_id: str, turn_id: str) -> str:
    return (
        "Before ending or compacting, call checkpoint_session with "
        f"session_id={session_id!r}, turn_id={turn_id!r}, and structured_state containing "
        "only objective, state, decisions, changed_files, validations, blockers, and next_steps. "
        "Never send the raw transcript or credentials."
    )


def handle_hook(event: str, client: str, stdin_text: str) -> tuple[int, str]:
    try:
        payload: dict[str, Any] = json.loads(stdin_text or "{}")
    except json.JSONDecodeError:
        payload = {}
    provider_session_id = str(payload.get("session_id") or "").strip()
    cwd = Path(str(payload.get("cwd") or Path.cwd()))
    turn_id = str(payload.get("turn_id") or "unknown")
    if not provider_session_id:
        return 0, ""
    try:
        config = load_config()
        if event == "session-start":
            source = str(payload.get("source") or payload.get("start_source") or "startup")
            context = open_session(
                config,
                provider=client,
                provider_session_id=provider_session_id,
                cwd=cwd,
                start_source=source,
            )
            _background_sync()
            message = f"emu-ai-mem session_id={context.session_id}."
            if context.capsule:
                message += " Continue from this bounded checkpoint:\n" + json.dumps(
                    context.capsule, ensure_ascii=False
                )
            else:
                message += " No earlier checkpoint was loaded."
            return 0, _client_output(client, event, message)
        session_id = provider_session(client, provider_session_id, cwd)
        if not session_id or checkpoint_for_turn(session_id, turn_id):
            return 0, ""
        if event == "pre-compact":
            return 0, _client_output(
                client, event, _checkpoint_instruction(session_id, turn_id)
            )
        if event == "stop" and claim_hook_retry(client, provider_session_id, turn_id):
            return 0, _client_output(
                client, event, _checkpoint_instruction(session_id, turn_id)
            )
        return 0, ""
    except Exception as exc:
        return 0, _client_output(client, event, f"emu-ai-mem warning: {exc}")
