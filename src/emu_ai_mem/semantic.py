from __future__ import annotations

import hashlib
import math
import struct
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

from .config import AppConfig
from .store import SearchResult, connect, transaction, utc_now


def queue_missing(*, db_path: Path | None = None) -> int:
    with transaction(db_path) as db:
        cursor = db.execute(
            "INSERT OR IGNORE INTO semantic_queue(memory_id,requested_at) "
            "SELECT m.id,? FROM memories m LEFT JOIN embeddings e ON e.memory_id=m.id "
            "WHERE e.memory_id IS NULL",
            (utc_now(),),
        )
        return cursor.rowcount


def start_background_index() -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(
            [sys.executable, "-m", "emu_ai_mem", "semantic-index"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
    except OSError:
        pass


def index_pending(
    config: AppConfig, *, batch_size: int = 128, db_path: Path | None = None
) -> int:
    try:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("Install emu-ai-mem[semantic] to build embeddings") from exc
    db = connect(db_path)
    try:
        rows = db.execute(
            "SELECT m.id,m.project,m.kind,m.tags_json,m.summary,m.details "
            "FROM semantic_queue q JOIN memories m ON m.id=q.memory_id "
            "ORDER BY q.requested_at LIMIT ?",
            (batch_size,),
        ).fetchall()
    finally:
        db.close()
    if not rows:
        return 0
    texts = [
        f"passage: {row['project']}\n{row['kind']} {row['tags_json']}\n"
        f"{row['summary']}\n{row['details']}"
        for row in rows
    ]
    model = TextEmbedding(model_name=config.model)
    vectors = list(model.embed(texts))
    with transaction(db_path) as db:
        for row, vector, text in zip(rows, vectors, texts, strict=True):
            values = [float(item) for item in vector]
            blob = struct.pack(f"<{len(values)}f", *values)
            db.execute(
                "INSERT OR REPLACE INTO embeddings VALUES(?,?,?,?,?)",
                (
                    row["id"],
                    config.model,
                    len(values),
                    blob,
                    hashlib.sha256(text.encode()).hexdigest(),
                ),
            )
            db.execute("DELETE FROM semantic_queue WHERE memory_id=?", (row["id"],))
    return len(rows)


def semantic_results(
    config: AppConfig,
    query: str,
    *,
    limit: int = 5,
    vaults: Iterable[str] | None = None,
    workspace_key: str | None = None,
    kinds: Iterable[str] | None = None,
    include_superseded: bool = False,
    db_path: Path | None = None,
) -> tuple[list[SearchResult], list[str]]:
    queue_missing(db_path=db_path)
    db = connect(db_path)
    try:
        clauses = ["e.model=?"]
        parameters: list[object] = [config.model]
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
        rows = db.execute(
            "SELECT m.*,w.workspace_key,e.dimension,e.vector FROM embeddings e "
            "JOIN memories m ON m.id=e.memory_id LEFT JOIN workspaces w ON w.id=m.workspace_id "
            "WHERE " + " AND ".join(clauses),
            tuple(parameters),
        ).fetchall()
    finally:
        db.close()
    if not rows:
        start_background_index()
        return [], ["Semantic index queued; no warm vectors were available"]
    try:
        from fastembed import TextEmbedding
    except ImportError:
        return [], ["Install emu-ai-mem[semantic] to query semantic memory"]
    embedded = iter(TextEmbedding(config.model).embed([f"query: {query}"]))
    query_vector = [float(item) for item in next(embedded)]

    def cosine(row: object) -> float:
        values = struct.unpack(f"<{row['dimension']}f", row["vector"])  # type: ignore[index]
        numerator = sum(left * right for left, right in zip(query_vector, values, strict=True))
        left_norm = math.sqrt(sum(value * value for value in query_vector))
        right_norm = math.sqrt(sum(value * value for value in values))
        return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0

    ranked = sorted(((cosine(row), row) for row in rows), reverse=True, key=lambda item: item[0])[:limit]
    return [
        SearchResult(
            vault=str(row["vault"]),
            id=str(row["id"]),
            workspace=row["workspace_key"],
            project=str(row["project"]),
            kind=str(row["kind"]),
            summary=str(row["summary"]),
            snippet=str(row["summary"]),
            created_at=str(row["created_at"]),
            superseded=bool(row["superseded"]),
            provenance=str(row["provenance"]),
            score=score,
        )
        for score, row in ranked
    ], []
