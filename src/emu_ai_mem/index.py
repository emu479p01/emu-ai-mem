from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import struct
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .config import AppConfig, VaultConfig
from .errors import RecordError
from .paths import index_path
from .records import MemoryRecord, iter_record_paths

Embedder = Callable[[Sequence[str]], list[list[float]]]


@dataclass(slots=True)
class SearchResult:
    vault: str
    id: str
    project: str
    tags: str
    summary: str
    score: float
    path: str


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or index_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(target)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            key TEXT PRIMARY KEY, vault TEXT NOT NULL, id TEXT NOT NULL,
            project TEXT NOT NULL, tags TEXT NOT NULL, summary TEXT NOT NULL,
            body TEXT NOT NULL, path TEXT NOT NULL, content_hash TEXT NOT NULL,
            superseded INTEGER NOT NULL DEFAULT 0, embedding BLOB,
            model TEXT, embed_dim INTEGER
        )
        """
    )
    db.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(key UNINDEXED, id, project, tags, summary, body)"
    )
    db.commit()
    return db


@lru_cache(maxsize=2)
def _embedding_model(model_name: str) -> Any:
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=model_name)


def default_embedder(model_name: str) -> Embedder:
    def embed(texts: Sequence[str]) -> list[list[float]]:
        model = _embedding_model(model_name)
        return [[float(value) for value in vector] for vector in model.embed(list(texts))]

    return embed


def _pack(vector: Sequence[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes, dimension: int) -> tuple[float, ...]:
    return struct.unpack(f"<{dimension}f", blob)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rebuild_index(
    config: AppConfig,
    *,
    db_path: Path | None = None,
    embedder: Embedder | None = None,
    full: bool = False,
) -> tuple[int, list[str]]:
    db = connect(db_path)
    existing = {
        row["key"]: row
        for row in db.execute(
            "SELECT key, content_hash, embedding, model, embed_dim FROM documents"
        ).fetchall()
    }
    warnings: list[str] = []
    parsed: list[tuple[VaultConfig, Path, MemoryRecord]] = []
    superseded: set[tuple[str, str]] = set()
    for vault in config.vaults.values():
        for path in iter_record_paths(vault.path):
            try:
                record = MemoryRecord.from_path(path)
            except RecordError as exc:
                warnings.append(str(exc))
                continue
            parsed.append((vault, path, record))
            superseded.update((vault.name, item) for item in record.supersedes)

    vectors: list[bytes | None] = [None] * len(parsed)
    hashes = [_hash(path) for _, path, _ in parsed]
    positions_to_embed: list[int] = []
    for position, (vault, _, record) in enumerate(parsed):
        key = f"{vault.name}:{record.id}"
        old = existing.get(key)
        if (
            not full
            and old is not None
            and old["content_hash"] == hashes[position]
            and old["embedding"] is not None
            and old["model"] == config.model
            and old["embed_dim"] == config.embed_dim
        ):
            vectors[position] = old["embedding"]
        else:
            positions_to_embed.append(position)

    embeddings_enabled = embedder is not None or os.environ.get("EMU_MEM_DISABLE_EMBEDDINGS") != "1"
    if positions_to_embed and embeddings_enabled:
        texts = [
            (
                f"passage: {parsed[position][2].project}\n"
                f"{' '.join(parsed[position][2].tags)}\n"
                f"{parsed[position][2].summary}\n{parsed[position][2].details}"
            )
            for position in positions_to_embed
        ]
        try:
            fn = embedder or default_embedder(config.model)
            embedded = fn(texts)
            if any(len(vector) != config.embed_dim for vector in embedded):
                raise ValueError(
                    f"Embedding dimension does not match configured {config.embed_dim}"
                )
            for position, vector in zip(positions_to_embed, embedded, strict=True):
                vectors[position] = _pack(vector)
        except Exception as exc:  # semantic search must degrade to local keyword search
            warnings.append(f"Semantic indexing unavailable; FTS index is usable: {exc}")

    db.execute("DELETE FROM documents")
    db.execute("DELETE FROM documents_fts")
    for position, (vault, path, record) in enumerate(parsed):
        key = f"{vault.name}:{record.id}"
        tags = ", ".join(record.tags)
        body = f"{record.summary}\n{record.details}"
        packed_vector = vectors[position]
        db.execute(
            "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key,
                vault.name,
                record.id,
                record.project,
                tags,
                record.summary,
                body,
                str(path),
                hashes[position],
                int((vault.name, record.id) in superseded),
                packed_vector,
                config.model if packed_vector is not None else None,
                config.embed_dim if packed_vector is not None else None,
            ),
        )
        db.execute(
            "INSERT INTO documents_fts(key, id, project, tags, summary, body) VALUES (?, ?, ?, ?, ?, ?)",
            (key, record.id, record.project, tags, record.summary, body),
        )
    db.commit()
    db.close()
    return len(parsed), warnings


def _fts_expression(query: str) -> str:
    words = [word.replace('"', '""') for word in query.split() if word]
    return " OR ".join(f'"{word}"' for word in words) or '""'


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def search_index(
    config: AppConfig,
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 5,
    vaults: Iterable[str] | None = None,
    include_superseded: bool = False,
    db_path: Path | None = None,
    embedder: Embedder | None = None,
) -> tuple[list[SearchResult], list[str]]:
    if mode not in {"fts", "vec", "hybrid"}:
        raise ValueError("mode must be fts, vec, or hybrid")
    db = connect(db_path)
    selected = set(vaults or config.vaults)
    allowed_clause = (
        " AND d.vault IN ({})".format(",".join("?" for _ in selected)) if selected else ""
    )
    superseded_clause = "" if include_superseded else " AND d.superseded = 0"
    scores: dict[str, float] = {}
    warnings: list[str] = []
    if mode in {"fts", "hybrid"}:
        rows = db.execute(
            "SELECT d.key FROM documents_fts f JOIN documents d ON d.key=f.key "
            f"WHERE documents_fts MATCH ?{allowed_clause}{superseded_clause} "
            "ORDER BY bm25(documents_fts) LIMIT ?",
            (_fts_expression(query), *sorted(selected), max(limit * 3, 10)),
        ).fetchall()
        for rank, row in enumerate(rows):
            scores[row["key"]] = scores.get(row["key"], 0.0) + 1.0 / (60 + rank)

    if mode in {"vec", "hybrid"}:
        try:
            fn = embedder or default_embedder(config.model)
            query_vector = fn([f"query: {query}"])[0]
            if len(query_vector) != config.embed_dim:
                raise ValueError("Query embedding dimension does not match the index")
            rows = db.execute(
                "SELECT key, embedding, embed_dim FROM documents d WHERE embedding IS NOT NULL"
                f"{allowed_clause}{superseded_clause}",
                tuple(sorted(selected)),
            ).fetchall()
            ranked = sorted(
                (
                    (_cosine(query_vector, _unpack(row["embedding"], row["embed_dim"])), row["key"])
                    for row in rows
                ),
                reverse=True,
            )[: max(limit * 3, 10)]
            for rank, (_, key) in enumerate(ranked):
                scores[key] = scores.get(key, 0.0) + 1.0 / (60 + rank)
        except Exception as exc:
            if mode == "vec":
                db.close()
                return [], [f"Semantic search unavailable: {exc}"]
            warnings.append(f"Semantic search unavailable; returned keyword results: {exc}")

    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    results: list[SearchResult] = []
    for key, score in ordered:
        row = db.execute("SELECT * FROM documents WHERE key = ?", (key,)).fetchone()
        if row:
            results.append(
                SearchResult(
                    vault=row["vault"],
                    id=row["id"],
                    project=row["project"],
                    tags=row["tags"],
                    summary=row["summary"],
                    score=score,
                    path=row["path"],
                )
            )
    db.close()
    return results, warnings
