from __future__ import annotations

import re
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter

from .config import AppConfig
from .errors import RecordError

CATEGORIES = {"projects", "sessions", "decisions"}


def string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value]
    raise RecordError(f"Expected a list of strings, got {type(value).__name__}")


def slugify(value: str) -> str:
    value = re.sub(r"[^\w.-]+", "-", value.strip().lower(), flags=re.UNICODE).strip("-")
    return value or "memory"


def generate_id(author_id: str, device_id: str, *, now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    timestamp = current.strftime("%Y%m%dT%H%M%S%fZ")
    return f"{timestamp}-{slugify(author_id)}-{slugify(device_id)}-{secrets.token_hex(3)}"


@dataclass(slots=True)
class MemoryRecord:
    id: str
    project: str
    tags: list[str]
    created_at: str
    author_id: str
    author_name: str
    device_id: str
    scope: str
    summary: str
    details: str
    supersedes: list[str] = field(default_factory=list)
    category: str = "sessions"

    def validate(self) -> None:
        if not self.id or not self.project or not self.summary.strip():
            raise RecordError("id, project, and summary are required")
        if self.scope not in {"personal", "team"}:
            raise RecordError("scope must be personal or team")
        if self.category not in CATEGORIES:
            raise RecordError(f"category must be one of: {', '.join(sorted(CATEGORIES))}")
        try:
            parsed = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RecordError("created_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None:
            raise RecordError("created_at must include a timezone")

    def to_markdown(self) -> str:
        self.validate()
        metadata: dict[str, Any] = {
            "schema_version": 1,
            "id": self.id,
            "project": self.project,
            "tags": self.tags,
            "created_at": self.created_at,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "device_id": self.device_id,
            "scope": self.scope,
            "supersedes": self.supersedes,
        }
        post = frontmatter.Post(
            f"## Summary\n{self.summary.strip()}\n\n## Details\n{self.details.strip()}\n",
            **metadata,
        )
        return frontmatter.dumps(post) + "\n"

    @classmethod
    def from_path(cls, path: Path) -> MemoryRecord:
        try:
            post = frontmatter.load(path)
            meta = post.metadata
            summary, details = split_body(post.content)
            record = cls(
                id=str(meta["id"]),
                project=str(meta["project"]),
                tags=string_list(meta.get("tags", [])),
                created_at=str(meta.get("created_at") or meta.get("created")),
                author_id=str(meta.get("author_id", "legacy")),
                author_name=str(meta.get("author_name", "Legacy import")),
                device_id=str(meta.get("device_id", "legacy")),
                scope=str(meta.get("scope", "personal")),
                summary=summary,
                details=details,
                supersedes=string_list(meta.get("supersedes", [])),
                category=path.parent.name if path.parent.name in CATEGORIES else "sessions",
            )
            record.validate()
            return record
        except (KeyError, TypeError, RecordError) as exc:
            raise RecordError(f"Invalid memory file {path}: {exc}") from exc


def split_body(body: str) -> tuple[str, str]:
    summary_match = re.search(r"(?s)(?:^|\n)## Summary\s*\n(.*?)(?=\n## Details\s*\n|\Z)", body)
    details_match = re.search(r"(?s)(?:^|\n)## Details\s*\n(.*)\Z", body)
    summary = summary_match.group(1).strip() if summary_match else body.strip()
    details = details_match.group(1).strip() if details_match else ""
    return summary, details


def create_record(
    config: AppConfig,
    *,
    project: str,
    tags: list[str],
    scope: str,
    summary: str,
    details: str,
    category: str = "sessions",
    supersedes: list[str] | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=generate_id(config.author_id, config.device_id),
        project=project,
        tags=tags,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        author_id=config.author_id,
        author_name=config.author_name,
        device_id=config.device_id,
        scope=scope,
        summary=summary,
        details=details,
        supersedes=supersedes or [],
        category=category,
    )


def write_record(vault_path: Path, record: MemoryRecord) -> Path:
    record.validate()
    directory = vault_path / "memories" / record.category
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record.id}.md"
    if path.exists():
        raise RecordError(f"Refusing to overwrite append-only memory: {path}")
    path.write_text(record.to_markdown(), encoding="utf-8")
    return path


def iter_record_paths(vault_path: Path) -> Iterator[Path]:
    memories = vault_path / "memories"
    if memories.exists():
        yield from sorted(memories.rglob("*.md"))
