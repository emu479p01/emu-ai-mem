from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
import uuid
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import AppConfig, VaultConfig
from .errors import ConfigurationError, RecordError
from .paths import state_path

CAPSULE_TOKEN_BUDGET = 600
CAPSULE_FIELDS = (
    "objective",
    "state",
    "decisions",
    "changed_files",
    "validations",
    "blockers",
    "next_steps",
)
SECRET_PATTERNS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(
        r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\b"
        r"\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:12]}"


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        result = value
        for pattern in SECRET_PATTERNS:
            result = pattern.sub("[REDACTED]", result)
        return result
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class MemoryResult:
    id: str
    vault: str
    workspace: str | None
    project: str
    kind: str
    summary: str
    created_at: str
    provenance: str


@dataclass(slots=True)
class SearchResult:
    vault: str
    id: str
    workspace: str | None
    project: str
    kind: str
    summary: str
    snippet: str
    created_at: str
    superseded: bool
    provenance: str
    score: float


@dataclass(slots=True)
class SessionContext:
    session_id: str
    workspace: str
    parent_session_id: str | None
    checkpoint_id: str | None
    capsule: dict[str, Any] | None
    estimated_tokens: int
    vault: str


SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS vaults (
    name TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('personal','team')),
    path TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY, workspace_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, provider TEXT NOT NULL, provider_session_id TEXT NOT NULL,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id),
    parent_session_id TEXT REFERENCES sessions(id), vault TEXT NOT NULL,
    started_at TEXT NOT NULL, last_active_at TEXT NOT NULL,
    UNIQUE(provider, provider_session_id, workspace_id)
);
CREATE INDEX IF NOT EXISTS sessions_workspace_recent
    ON sessions(workspace_id, last_active_at DESC);
CREATE TABLE IF NOT EXISTS checkpoints (
    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
    turn_id TEXT NOT NULL, vault TEXT NOT NULL, created_at TEXT NOT NULL,
    capsule_json TEXT NOT NULL, token_estimate INTEGER NOT NULL,
    event_id TEXT NOT NULL UNIQUE, UNIQUE(session_id, turn_id)
);
CREATE INDEX IF NOT EXISTS checkpoints_session_recent
    ON checkpoints(session_id, created_at DESC);
CREATE TABLE IF NOT EXISTS session_injections (
    session_id TEXT NOT NULL, checkpoint_id TEXT NOT NULL,
    start_source TEXT NOT NULL, injected_at TEXT NOT NULL,
    PRIMARY KEY(session_id, checkpoint_id)
);
CREATE TABLE IF NOT EXISTS hook_attempts (
    provider TEXT NOT NULL, provider_session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL, attempted_at TEXT NOT NULL,
    PRIMARY KEY(provider, provider_session_id, turn_id)
);
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY, vault TEXT NOT NULL,
    workspace_id TEXT REFERENCES workspaces(id), project TEXT NOT NULL,
    kind TEXT NOT NULL, tags_json TEXT NOT NULL, summary TEXT NOT NULL,
    details TEXT NOT NULL, created_at TEXT NOT NULL, author_id TEXT NOT NULL,
    author_name TEXT NOT NULL, device_id TEXT NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0, supersedes_json TEXT NOT NULL,
    event_id TEXT NOT NULL UNIQUE, provenance TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS memories_filters
    ON memories(vault, workspace_id, kind, created_at DESC, superseded);
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    id UNINDEXED, project, kind, tags, summary, details,
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid,id,project,kind,tags,summary,details)
    VALUES (new.rowid,new.id,new.project,new.kind,new.tags_json,new.summary,new.details);
END;
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, vault TEXT NOT NULL, event_type TEXT NOT NULL,
    entity_id TEXT NOT NULL, created_at TEXT NOT NULL, device_id TEXT NOT NULL,
    payload_json TEXT NOT NULL, imported INTEGER NOT NULL DEFAULT 0,
    exported_segment TEXT
);
CREATE INDEX IF NOT EXISTS events_vault_created ON events(vault, created_at);
CREATE TABLE IF NOT EXISTS outbox (
    event_id TEXT PRIMARY KEY REFERENCES events(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imported_segments (
    vault TEXT NOT NULL, segment_id TEXT NOT NULL, content_hash TEXT NOT NULL,
    imported_at TEXT NOT NULL, PRIMARY KEY(vault, segment_id)
);
CREATE TABLE IF NOT EXISTS migration_sources (
    vault TEXT NOT NULL, source_path TEXT NOT NULL, content_hash TEXT NOT NULL,
    entity_id TEXT NOT NULL, imported_at TEXT NOT NULL,
    PRIMARY KEY(vault, source_path, content_hash)
);
CREATE TABLE IF NOT EXISTS sync_state (
    vault TEXT PRIMARY KEY, last_sync_at TEXT, last_status TEXT
);
CREATE TABLE IF NOT EXISTS embeddings (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id), model TEXT NOT NULL,
    dimension INTEGER NOT NULL, vector BLOB NOT NULL, content_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS semantic_queue (
    memory_id TEXT PRIMARY KEY REFERENCES memories(id), requested_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS supersessions (
    old_memory_id TEXT NOT NULL, new_memory_id TEXT NOT NULL,
    PRIMARY KEY(old_memory_id,new_memory_id)
);
CREATE TABLE IF NOT EXISTS deferred_events (
    event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS session_links (
    session_id TEXT PRIMARY KEY, parent_session_id TEXT NOT NULL
);
PRAGMA user_version = 2;
"""


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or state_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA)
    return db


@contextmanager
def transaction(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    db = connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def register_config(config: AppConfig, *, db_path: Path | None = None) -> None:
    with transaction(db_path) as db:
        for vault in config.vaults.values():
            db.execute(
                "INSERT INTO vaults(name,kind,path) VALUES(?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,path=excluded.path",
                (vault.name, vault.kind, str(vault.path)),
            )


def personal_vault(config: AppConfig) -> VaultConfig:
    if config.default_vault:
        default = config.vaults.get(config.default_vault)
        if default and default.kind == "personal":
            return default
    personal = sorted(
        (vault for vault in config.vaults.values() if vault.kind == "personal"),
        key=lambda value: value.name,
    )
    if not personal:
        raise ConfigurationError(
            "Automatic session checkpoints require a personal vault; "
            "emu-ai-mem will never fall back to a team vault"
        )
    return personal[0]


def _run_git(cwd: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=5
    )
    return result.stdout.strip() if result.returncode == 0 else None


def canonical_workspace(cwd: Path | str) -> tuple[str, str]:
    location = Path(cwd).expanduser().resolve()
    root_text = _run_git(location, "rev-parse", "--show-toplevel")
    root = Path(root_text).resolve() if root_text else location
    remote = _run_git(root, "remote", "get-url", "origin")
    if remote:
        sanitized = re.sub(r"https?://[^/@]+@", "https://", remote.strip())
        sanitized = re.sub(r"^git@([^:]+):", r"ssh://\1/", sanitized)
        sanitized = sanitized.removesuffix(".git").rstrip("/").lower()
        key_source = f"git:{sanitized}"
        display = sanitized.rsplit("/", 1)[-1]
    else:
        key_source = f"path:{str(root).casefold()}"
        display = root.name or "workspace"
    digest = hashlib.sha256(key_source.encode()).hexdigest()[:24]
    return f"ws_{digest}", display


def ensure_workspace(
    db: sqlite3.Connection, workspace_key: str, display_name: str | None = None
) -> str:
    row = db.execute(
        "SELECT id FROM workspaces WHERE workspace_key=?", (workspace_key,)
    ).fetchone()
    if row:
        return str(row["id"])
    workspace_id = new_id("ws")
    db.execute(
        "INSERT INTO workspaces VALUES(?,?,?,?)",
        (workspace_id, workspace_key, display_name or workspace_key, utc_now()),
    )
    return workspace_id


def _event(
    db: sqlite3.Connection,
    *,
    vault: str,
    event_type: str,
    entity_id: str,
    device_id: str,
    payload: Mapping[str, Any],
    event_id: str | None = None,
    created_at: str | None = None,
    imported: bool = False,
) -> str:
    identifier = event_id or new_id("evt")
    timestamp = created_at or utc_now()
    db.execute(
        "INSERT INTO events(id,vault,event_type,entity_id,created_at,device_id,payload_json,imported) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (
            identifier,
            vault,
            event_type,
            entity_id,
            timestamp,
            device_id,
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
            int(imported),
        ),
    )
    if not imported:
        db.execute(
            "INSERT INTO outbox(event_id,created_at) VALUES(?,?)", (identifier, timestamp)
        )
    return identifier


def remember_memory(
    config: AppConfig,
    *,
    vault_name: str,
    project: str,
    summary: str,
    details: str = "",
    kind: str = "fact",
    tags: Sequence[str] = (),
    workspace_key: str | None = None,
    supersedes: Sequence[str] = (),
    memory_id: str | None = None,
    created_at: str | None = None,
    provenance: str = "local",
    db_path: Path | None = None,
) -> MemoryResult:
    if vault_name not in config.vaults:
        raise ConfigurationError(f"Unknown vault: {vault_name}")
    if not summary.strip() or not project.strip():
        raise RecordError("project and summary are required")
    if contains_secret(summary) or contains_secret(details):
        raise RecordError("Refusing to store content that appears to contain a credential")
    identifier = memory_id or new_id("mem")
    timestamp = created_at or utc_now()
    with transaction(db_path) as db:
        vault = config.vaults[vault_name]
        db.execute(
            "INSERT INTO vaults(name,kind,path) VALUES(?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET kind=excluded.kind,path=excluded.path",
            (vault.name, vault.kind, str(vault.path)),
        )
        workspace_id = (
            ensure_workspace(db, workspace_key, workspace_key) if workspace_key else None
        )
        payload: dict[str, Any] = {
            "id": identifier,
            "vault": vault_name,
            "workspace_key": workspace_key,
            "project": project.strip(),
            "kind": kind,
            "tags": list(tags),
            "summary": summary.strip(),
            "details": details.strip(),
            "created_at": timestamp,
            "author_id": config.author_id,
            "author_name": config.author_name,
            "device_id": config.device_id,
            "supersedes": list(supersedes),
            "provenance": provenance,
        }
        event_id = _event(
            db,
            vault=vault_name,
            event_type="memory.created",
            entity_id=identifier,
            device_id=config.device_id,
            payload=payload,
            created_at=timestamp,
        )
        db.execute(
            "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                identifier,
                vault_name,
                workspace_id,
                project.strip(),
                kind,
                json.dumps(list(tags), ensure_ascii=False),
                summary.strip(),
                details.strip(),
                timestamp,
                config.author_id,
                config.author_name,
                config.device_id,
                0,
                json.dumps(list(supersedes)),
                event_id,
                provenance,
            ),
        )
        for old_id in supersedes:
            db.execute(
                "INSERT OR IGNORE INTO supersessions VALUES(?,?)", (old_id, identifier)
            )
            db.execute("UPDATE memories SET superseded=1 WHERE id=?", (old_id,))
    return MemoryResult(
        id=identifier,
        vault=vault_name,
        workspace=workspace_key,
        project=project.strip(),
        kind=kind,
        summary=summary.strip(),
        created_at=timestamp,
        provenance=provenance,
    )


def _fts_expression(query: str) -> str:
    words = re.findall(r"[\w.-]+", query, flags=re.UNICODE)
    return " OR ".join(f'"{word}"' for word in words)


def search_memories(
    query: str,
    *,
    limit: int = 5,
    vaults: Iterable[str] | None = None,
    workspace_key: str | None = None,
    kinds: Iterable[str] | None = None,
    include_superseded: bool = False,
    db_path: Path | None = None,
) -> list[SearchResult]:
    expression = _fts_expression(query)
    if not expression:
        return []
    clauses = ["memories_fts MATCH ?"]
    parameters: list[Any] = [expression]
    selected_vaults = sorted(set(vaults or ()))
    selected_kinds = sorted(set(kinds or ()))
    if selected_vaults:
        clauses.append(f"m.vault IN ({','.join('?' for _ in selected_vaults)})")
        parameters.extend(selected_vaults)
    if selected_kinds:
        clauses.append(f"m.kind IN ({','.join('?' for _ in selected_kinds)})")
        parameters.extend(selected_kinds)
    if workspace_key:
        clauses.append("w.workspace_key=?")
        parameters.append(workspace_key)
    if not include_superseded:
        clauses.append("m.superseded=0")
    parameters.append(max(1, min(limit, 100)))
    db = connect(db_path)
    try:
        rows = db.execute(
            "SELECT m.*,w.workspace_key,bm25(memories_fts) AS rank,"
            "snippet(memories_fts,5,'[',']',' … ',24) AS hit "
            "FROM memories_fts JOIN memories m ON m.rowid=memories_fts.rowid "
            "LEFT JOIN workspaces w ON w.id=m.workspace_id WHERE "
            + " AND ".join(clauses)
            + " ORDER BY rank,m.created_at DESC LIMIT ?",
            tuple(parameters),
        ).fetchall()
        return [
            SearchResult(
                vault=str(row["vault"]),
                id=str(row["id"]),
                workspace=row["workspace_key"],
                project=str(row["project"]),
                kind=str(row["kind"]),
                summary=str(row["summary"]),
                snippet=str(row["hit"] or row["summary"]),
                created_at=str(row["created_at"]),
                superseded=bool(row["superseded"]),
                provenance=str(row["provenance"]),
                score=-float(row["rank"]),
            )
            for row in rows
        ]
    finally:
        db.close()


def estimate_tokens(value: Mapping[str, Any]) -> int:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return max(1, (len(text) + 3) // 4)


def normalize_capsule(
    state: Mapping[str, Any], *, budget: int = CAPSULE_TOKEN_BUDGET
) -> tuple[dict[str, Any], int]:
    capsule: dict[str, Any] = {}
    for field in CAPSULE_FIELDS:
        value = _redact(state.get(field))
        if value not in (None, "", []):
            capsule[field] = value
    while estimate_tokens(capsule) > budget:
        reduced = False
        for field in reversed(CAPSULE_FIELDS):
            value = capsule.get(field)
            if isinstance(value, list) and len(value) > 1:
                capsule[field] = value[:-1]
                reduced = True
                break
            if isinstance(value, str) and len(value) > 80:
                capsule[field] = value[: max(80, len(value) - 160)].rstrip() + "…"
                reduced = True
                break
        if not reduced:
            break
    return capsule, estimate_tokens(capsule)


def open_session(
    config: AppConfig,
    *,
    provider: str,
    provider_session_id: str,
    cwd: Path | str,
    start_source: str = "startup",
    db_path: Path | None = None,
) -> SessionContext:
    vault = personal_vault(config)
    workspace_key, display = canonical_workspace(cwd)
    with transaction(db_path) as db:
        workspace_id = ensure_workspace(db, workspace_key, display)
        existing = db.execute(
            "SELECT * FROM sessions WHERE provider=? AND provider_session_id=? AND workspace_id=?",
            (provider, provider_session_id, workspace_id),
        ).fetchone()
        parent_id: str | None = None
        if existing and start_source in {"resume", "compact"}:
            session_id = str(existing["id"])
            parent_id = existing["parent_session_id"]
            db.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (utc_now(), session_id))
        else:
            parent = db.execute(
                "SELECT id FROM sessions WHERE workspace_id=? ORDER BY last_active_at DESC LIMIT 1",
                (workspace_id,),
            ).fetchone()
            parent_id = str(parent["id"]) if parent else None
            session_id = new_id("ses")
            timestamp = utc_now()
            payload = {
                "id": session_id,
                "provider": provider,
                "provider_session_id": provider_session_id,
                "workspace_key": workspace_key,
                "parent_session_id": parent_id,
                "vault": vault.name,
                "started_at": timestamp,
            }
            _event(
                db,
                vault=vault.name,
                event_type="session.opened",
                entity_id=session_id,
                device_id=config.device_id,
                payload=payload,
                created_at=timestamp,
            )
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    provider,
                    provider_session_id,
                    workspace_id,
                    parent_id,
                    vault.name,
                    timestamp,
                    timestamp,
                ),
            )
        checkpoint = db.execute(
            "SELECT c.* FROM checkpoints c JOIN sessions s ON s.id=c.session_id "
            "WHERE s.workspace_id=? AND (c.session_id=? OR c.session_id=?) "
            "ORDER BY c.created_at DESC LIMIT 1",
            (workspace_id, session_id, parent_id),
        ).fetchone()
        capsule: dict[str, Any] | None = None
        checkpoint_id: str | None = None
        tokens = 0
        if checkpoint:
            checkpoint_id = str(checkpoint["id"])
            injected = db.execute(
                "SELECT 1 FROM session_injections WHERE session_id=? AND checkpoint_id=?",
                (session_id, checkpoint_id),
            ).fetchone()
            if not injected or start_source == "compact":
                capsule = json.loads(str(checkpoint["capsule_json"]))
                tokens = int(checkpoint["token_estimate"])
                db.execute(
                    "INSERT OR IGNORE INTO session_injections VALUES(?,?,?,?)",
                    (session_id, checkpoint_id, start_source, utc_now()),
                )
        return SessionContext(
            session_id=session_id,
            workspace=workspace_key,
            parent_session_id=parent_id,
            checkpoint_id=checkpoint_id,
            capsule=capsule,
            estimated_tokens=tokens,
            vault=vault.name,
        )


def checkpoint_session(
    config: AppConfig,
    *,
    session_id: str,
    turn_id: str,
    structured_state: Mapping[str, Any],
    db_path: Path | None = None,
) -> dict[str, Any]:
    vault = personal_vault(config)
    capsule, tokens = normalize_capsule(structured_state)
    with transaction(db_path) as db:
        session = db.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            raise RecordError(f"Unknown session: {session_id}")
        existing = db.execute(
            "SELECT * FROM checkpoints WHERE session_id=? AND turn_id=?",
            (session_id, turn_id),
        ).fetchone()
        if existing:
            return {
                "checkpoint_id": str(existing["id"]),
                "session_id": session_id,
                "turn_id": turn_id,
                "estimated_tokens": int(existing["token_estimate"]),
                "idempotent": True,
            }
        checkpoint_id = new_id("chk")
        timestamp = utc_now()
        payload = {
            "id": checkpoint_id,
            "session_id": session_id,
            "turn_id": turn_id,
            "vault": vault.name,
            "created_at": timestamp,
            "capsule": capsule,
            "token_estimate": tokens,
        }
        event_id = _event(
            db,
            vault=vault.name,
            event_type="checkpoint.created",
            entity_id=checkpoint_id,
            device_id=config.device_id,
            payload=payload,
            created_at=timestamp,
        )
        db.execute(
            "INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?)",
            (
                checkpoint_id,
                session_id,
                turn_id,
                vault.name,
                timestamp,
                json.dumps(capsule, ensure_ascii=False, sort_keys=True),
                tokens,
                event_id,
            ),
        )
        db.execute("UPDATE sessions SET last_active_at=? WHERE id=?", (timestamp, session_id))
    return {
        "checkpoint_id": checkpoint_id,
        "session_id": session_id,
        "turn_id": turn_id,
        "estimated_tokens": tokens,
        "idempotent": False,
    }


def latest_session_context(
    workspace: str, *, db_path: Path | None = None
) -> SessionContext | None:
    db = connect(db_path)
    try:
        row = db.execute(
            "SELECT s.*,w.workspace_key FROM sessions s JOIN workspaces w ON w.id=s.workspace_id "
            "WHERE w.workspace_key=? OR w.id=? ORDER BY s.last_active_at DESC LIMIT 1",
            (workspace, workspace),
        ).fetchone()
        if not row:
            return None
        checkpoint = db.execute(
            "SELECT * FROM checkpoints WHERE session_id=? ORDER BY created_at DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        return SessionContext(
            session_id=str(row["id"]),
            workspace=str(row["workspace_key"]),
            parent_session_id=row["parent_session_id"],
            checkpoint_id=str(checkpoint["id"]) if checkpoint else None,
            capsule=json.loads(str(checkpoint["capsule_json"])) if checkpoint else None,
            estimated_tokens=int(checkpoint["token_estimate"]) if checkpoint else 0,
            vault=str(row["vault"]),
        )
    finally:
        db.close()


def provider_session(
    provider: str,
    provider_session_id: str,
    cwd: Path | str,
    *,
    db_path: Path | None = None,
) -> str | None:
    workspace_key, _ = canonical_workspace(cwd)
    db = connect(db_path)
    try:
        row = db.execute(
            "SELECT s.id FROM sessions s JOIN workspaces w ON w.id=s.workspace_id "
            "WHERE s.provider=? AND s.provider_session_id=? AND w.workspace_key=?",
            (provider, provider_session_id, workspace_key),
        ).fetchone()
        return str(row["id"]) if row else None
    finally:
        db.close()


def checkpoint_for_turn(
    session_id: str, turn_id: str, *, db_path: Path | None = None
) -> bool:
    db = connect(db_path)
    try:
        return (
            db.execute(
                "SELECT 1 FROM checkpoints WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            ).fetchone()
            is not None
        )
    finally:
        db.close()


def claim_hook_retry(
    provider: str,
    provider_session_id: str,
    turn_id: str,
    *,
    db_path: Path | None = None,
) -> bool:
    with transaction(db_path) as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO hook_attempts VALUES(?,?,?,?)",
            (provider, provider_session_id, turn_id, utc_now()),
        )
        return cursor.rowcount == 1


def publish_handoff(
    config: AppConfig,
    *,
    checkpoint_id: str,
    team_vault: str,
    project: str,
    db_path: Path | None = None,
) -> MemoryResult:
    if team_vault not in config.vaults or config.vaults[team_vault].kind != "team":
        raise ConfigurationError("publish_handoff requires an explicit team vault")
    db = connect(db_path)
    try:
        row = db.execute(
            "SELECT c.*,w.workspace_key FROM checkpoints c JOIN sessions s ON s.id=c.session_id "
            "JOIN workspaces w ON w.id=s.workspace_id WHERE c.id=?",
            (checkpoint_id,),
        ).fetchone()
        if not row:
            raise RecordError(f"Unknown checkpoint: {checkpoint_id}")
        capsule = json.loads(str(row["capsule_json"]))
        objective = str(capsule.get("objective") or "Session handoff")
        details = json.dumps(capsule, ensure_ascii=False, indent=2)
        workspace_key = str(row["workspace_key"])
    finally:
        db.close()
    return remember_memory(
        config,
        vault_name=team_vault,
        project=project,
        summary=objective,
        details=details,
        kind="handoff",
        tags=("handoff",),
        workspace_key=workspace_key,
        provenance=f"checkpoint:{checkpoint_id}",
        db_path=db_path,
    )


def event_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "id": row["id"],
        "vault": row["vault"],
        "event_type": row["event_type"],
        "entity_id": row["entity_id"],
        "created_at": row["created_at"],
        "device_id": row["device_id"],
        "payload": json.loads(str(row["payload_json"])),
    }


def apply_imported_event(db: sqlite3.Connection, event: Mapping[str, Any]) -> bool:
    event_id = str(event["id"])
    if db.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone():
        return False
    payload = dict(event["payload"])
    event_type = str(event["event_type"])
    _event(
        db,
        vault=str(event["vault"]),
        event_type=event_type,
        entity_id=str(event["entity_id"]),
        device_id=str(event["device_id"]),
        payload=payload,
        event_id=event_id,
        created_at=str(event["created_at"]),
        imported=True,
    )
    if event_type == "memory.created":
        workspace_key = payload.get("workspace_key")
        workspace_id = (
            ensure_workspace(db, str(workspace_key), str(workspace_key))
            if workspace_key
            else None
        )
        if not db.execute("SELECT 1 FROM memories WHERE id=?", (payload["id"],)).fetchone():
            is_superseded = db.execute(
                "SELECT 1 FROM supersessions WHERE old_memory_id=?", (payload["id"],)
            ).fetchone()
            db.execute(
                "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["id"],
                    payload["vault"],
                    workspace_id,
                    payload["project"],
                    payload["kind"],
                    json.dumps(payload.get("tags", []), ensure_ascii=False),
                    payload["summary"],
                    payload.get("details", ""),
                    payload["created_at"],
                    payload["author_id"],
                    payload["author_name"],
                    payload["device_id"],
                    int(is_superseded is not None),
                    json.dumps(payload.get("supersedes", [])),
                    event_id,
                    payload.get("provenance", "git"),
                ),
            )
            for old_id in payload.get("supersedes", []):
                db.execute(
                    "INSERT OR IGNORE INTO supersessions VALUES(?,?)",
                    (old_id, payload["id"]),
                )
                db.execute("UPDATE memories SET superseded=1 WHERE id=?", (old_id,))
    elif event_type == "session.opened":
        workspace_id = ensure_workspace(db, payload["workspace_key"], payload["workspace_key"])
        requested_parent = payload.get("parent_session_id")
        available_parent = None
        if requested_parent and db.execute(
            "SELECT 1 FROM sessions WHERE id=?", (requested_parent,)
        ).fetchone():
            available_parent = requested_parent
        db.execute(
            "INSERT OR IGNORE INTO sessions VALUES(?,?,?,?,?,?,?,?)",
            (
                payload["id"],
                payload["provider"],
                payload["provider_session_id"],
                workspace_id,
                available_parent,
                payload["vault"],
                payload["started_at"],
                payload["started_at"],
            ),
        )
        if requested_parent and not available_parent:
            db.execute(
                "INSERT OR REPLACE INTO session_links VALUES(?,?)",
                (payload["id"], requested_parent),
            )
        db.execute(
            "UPDATE sessions SET parent_session_id=? WHERE id IN "
            "(SELECT session_id FROM session_links WHERE parent_session_id=?)",
            (payload["id"], payload["id"]),
        )
        db.execute("DELETE FROM session_links WHERE parent_session_id=?", (payload["id"],))
        deferred = db.execute(
            "SELECT event_id,payload_json FROM deferred_events WHERE event_type='checkpoint.created'"
        ).fetchall()
        for pending in deferred:
            pending_payload = json.loads(str(pending["payload_json"]))
            if pending_payload["session_id"] == payload["id"]:
                db.execute(
                    "INSERT OR IGNORE INTO checkpoints VALUES(?,?,?,?,?,?,?,?)",
                    (
                        pending_payload["id"],
                        pending_payload["session_id"],
                        pending_payload["turn_id"],
                        pending_payload["vault"],
                        pending_payload["created_at"],
                        json.dumps(pending_payload["capsule"], ensure_ascii=False, sort_keys=True),
                        pending_payload["token_estimate"],
                        pending["event_id"],
                    ),
                )
                db.execute("DELETE FROM deferred_events WHERE event_id=?", (pending["event_id"],))
    elif event_type == "checkpoint.created":
        if db.execute("SELECT 1 FROM sessions WHERE id=?", (payload["session_id"],)).fetchone():
            db.execute(
                "INSERT OR IGNORE INTO checkpoints VALUES(?,?,?,?,?,?,?,?)",
                (
                    payload["id"],
                    payload["session_id"],
                    payload["turn_id"],
                    payload["vault"],
                    payload["created_at"],
                    json.dumps(payload["capsule"], ensure_ascii=False, sort_keys=True),
                    payload["token_estimate"],
                    event_id,
                ),
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO deferred_events VALUES(?,?,?)",
                (event_id, event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
    return True


def as_public_dict(value: MemoryResult | SearchResult | SessionContext) -> dict[str, Any]:
    return asdict(value)
