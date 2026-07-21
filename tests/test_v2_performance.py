from __future__ import annotations

import time
from pathlib import Path

from emu_ai_mem.store import connect


def test_ten_thousand_record_hot_paths_stay_indexed(tmp_path: Path) -> None:
    db = connect(tmp_path / "performance.db")
    with db:
        db.execute("INSERT INTO workspaces VALUES('workspace','bench','bench','2026-01-01Z')")
        db.executemany(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?)",
            (
                (
                    f"session-{index}",
                    "codex",
                    f"provider-{index}",
                    "workspace",
                    None,
                    "personal",
                    f"2026-01-01T00:00:{index % 60:02d}Z",
                    f"2026-01-01T00:{index // 60 % 60:02d}:{index % 60:02d}Z",
                )
                for index in range(10_000)
            ),
        )
        db.executemany(
            "INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                (
                    f"memory-{index}",
                    "personal",
                    "workspace",
                    "bench",
                    "fact",
                    "[]",
                    f"benchmark memory {index}",
                    "needle context" if index == 9_999 else "other context",
                    "2026-01-01T00:00:00Z",
                    "alice",
                    "Alice",
                    "device",
                    0,
                    "[]",
                    f"event-{index}",
                    "benchmark",
                )
                for index in range(10_000)
            ),
        )
    started = time.perf_counter()
    db.execute(
        "SELECT id FROM sessions WHERE workspace_id=? ORDER BY last_active_at DESC LIMIT 1",
        ("workspace",),
    ).fetchone()
    resume_ms = (time.perf_counter() - started) * 1000
    started = time.perf_counter()
    db.execute(
        "SELECT m.id FROM memories_fts JOIN memories m ON m.rowid=memories_fts.rowid "
        "WHERE memories_fts MATCH ? LIMIT 5",
        ("needle",),
    ).fetchall()
    search_ms = (time.perf_counter() - started) * 1000
    db.close()
    assert resume_ms < 50
    assert search_ms < 150
