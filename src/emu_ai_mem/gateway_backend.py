from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from .config import AppConfig, VaultConfig
from .gateway_auth import GatewayOAuthProvider
from .store import apply_imported_event, connect, event_dict, transaction, utc_now


class GitHubGatewayBackend:
    def __init__(self, provider: GatewayOAuthProvider, root: Path) -> None:
        self.provider = provider
        self.root = root

    def tenant_db(self, subject: str) -> Path:
        digest = hashlib.sha256(subject.encode()).hexdigest()[:24]
        return self.root / "tenants" / digest / "state.sqlite3"

    def config(self, subject: str) -> AppConfig:
        vaults = {
            item["name"]: VaultConfig(
                name=item["name"],
                url=f"https://github.com/{item['repository']}.git",
                path=Path("/remote") / item["name"],
                kind=item["kind"],
            )
            for item in self.provider.vaults(subject)
        }
        personal = next((name for name, vault in vaults.items() if vault.kind == "personal"), None)
        return AppConfig(
            author_id=subject,
            author_name=subject,
            device_id=f"gateway-{hashlib.sha256(subject.encode()).hexdigest()[:10]}",
            default_vault=personal or next(iter(vaults), None),
            vaults=vaults,
        )

    async def verify_repository(self, subject: str, repository: str) -> dict[str, Any]:
        token = await self.provider.github_token(subject)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"https://api.github.com/repos/{repository}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            data = response.json()
            permissions = data.get("permissions") or {}
            return {
                "repository": data["full_name"],
                "private": bool(data["private"]),
                "can_pull": bool(permissions.get("pull", True)),
                "can_push": bool(permissions.get("push", False)),
                "default_branch": data.get("default_branch", "main"),
            }

    async def refresh(self, subject: str, vault_name: str | None = None) -> dict[str, Any]:
        token = await self.provider.github_token(subject)
        selected = [
            item
            for item in self.provider.vaults(subject)
            if vault_name is None or item["name"] == vault_name
        ]
        imported = 0
        warnings: list[str] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for vault in selected:
                repository = vault["repository"]
                repo = await self.verify_repository(subject, repository)
                tree = await client.get(
                    f"https://api.github.com/repos/{repository}/git/trees/{repo['default_branch']}",
                    params={"recursive": "1"},
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                )
                tree.raise_for_status()
                entries = [
                    item
                    for item in tree.json().get("tree", [])
                    if item.get("type") == "blob"
                    and str(item.get("path", "")).startswith("events/v2/")
                    and str(item.get("path", "")).endswith(".jsonl")
                ]
                for entry in entries:
                    segment_id = str(entry["path"])
                    sha = str(entry["sha"])
                    db = connect(self.tenant_db(subject))
                    try:
                        known = db.execute(
                            "SELECT content_hash FROM imported_segments WHERE vault=? AND segment_id=?",
                            (vault["name"], segment_id),
                        ).fetchone()
                    finally:
                        db.close()
                    if known:
                        if str(known["content_hash"]) != sha:
                            warnings.append(f"Immutable segment changed: {segment_id}")
                        continue
                    blob = await client.get(
                        str(entry["url"]),
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                    )
                    blob.raise_for_status()
                    content = base64.b64decode(blob.json()["content"])
                    try:
                        events = [json.loads(line) for line in content.decode().splitlines() if line]
                        with transaction(self.tenant_db(subject)) as tx:
                            for event in events:
                                if event.get("schema_version") != 2:
                                    raise ValueError("unsupported schema version")
                                imported += int(apply_imported_event(tx, event))
                            tx.execute(
                                "INSERT INTO imported_segments VALUES(?,?,?,?)",
                                (vault["name"], segment_id, sha, utc_now()),
                            )
                    except (ValueError, KeyError, json.JSONDecodeError) as exc:
                        warnings.append(f"Invalid segment {segment_id}: {exc}")
        return {"imported": imported, "warnings": warnings}

    async def flush(self, subject: str, vault_name: str) -> dict[str, Any]:
        vault = next(
            (item for item in self.provider.vaults(subject) if item["name"] == vault_name),
            None,
        )
        if not vault:
            raise ValueError(f"Unknown gateway vault: {vault_name}")
        db_path = self.tenant_db(subject)
        db = connect(db_path)
        try:
            rows = db.execute(
                "SELECT e.* FROM outbox o JOIN events e ON e.id=o.event_id "
                "WHERE e.vault=? AND e.exported_segment IS NULL ORDER BY e.created_at,e.id",
                (vault_name,),
            ).fetchall()
        finally:
            db.close()
        if not rows:
            return {"exported": 0}
        config = self.config(subject)
        timestamp = datetime.now(UTC)
        segment = (
            f"events/v2/{config.device_id}/{timestamp.strftime('%Y-%m')}/"
            f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{config.device_id}.jsonl"
        )
        content = "".join(
            json.dumps(event_dict(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        )
        token = await self.provider.github_token(subject)
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.put(
                f"https://api.github.com/repos/{vault['repository']}/contents/{segment}",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
                json={
                    "message": f"events: {Path(segment).stem}",
                    "content": base64.b64encode(content.encode()).decode(),
                },
            )
            response.raise_for_status()
        with transaction(db_path) as tx:
            tx.executemany(
                "UPDATE events SET exported_segment=? WHERE id=?",
                [(segment, row["id"]) for row in rows],
            )
            tx.executemany("DELETE FROM outbox WHERE event_id=?", [(row["id"],) for row in rows])
        return {"exported": len(rows), "segment": segment}
