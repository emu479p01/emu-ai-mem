from __future__ import annotations

from pathlib import Path

from emu_ai_mem.config import AppConfig, VaultConfig
from emu_ai_mem.index import rebuild_index, search_index
from emu_ai_mem.records import MemoryRecord, write_record


def _record(memory_id: str, summary: str, *, supersedes: list[str] | None = None) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        project="payments",
        tags=["architecture"],
        created_at="2026-07-21T00:00:00Z",
        author_id="chai",
        author_name="Chai",
        device_id="laptop",
        scope="team",
        summary=summary,
        details="รายละเอียด multilingual context",
        supersedes=supersedes or [],
        category="decisions",
    )


def _embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    for text in texts:
        lower = text.lower()
        if "payment" in lower or "ชำระ" in text or "pagamento" in lower:
            vectors.append([1.0, 0.0, 0.0, 0.0])
        else:
            vectors.append([0.0, 1.0, 0.0, 0.0])
    return vectors


def test_multi_vault_search_provenance_and_supersede(tmp_path: Path) -> None:
    personal = tmp_path / "personal"
    team = tmp_path / "team"
    write_record(personal, _record("personal-1", "Private payment note"))
    write_record(team, _record("old", "Old payment policy"))
    write_record(team, _record("new", "Current payment policy", supersedes=["old"]))
    config = AppConfig(
        author_id="chai",
        author_name="Chai",
        device_id="dev",
        default_vault="personal",
        embed_dim=4,
        vaults={
            "personal": VaultConfig("personal", "url1", personal, "personal"),
            "team": VaultConfig("team", "url2", team, "team"),
        },
    )
    db = tmp_path / "index.db"
    count, warnings = rebuild_index(config, db_path=db, embedder=_embed)
    assert count == 3
    assert not warnings

    results, warnings = search_index(
        config, "นโยบายการชำระเงิน", db_path=db, embedder=_embed, limit=10
    )
    assert not warnings
    assert {result.vault for result in results} == {"personal", "team"}
    assert "old" not in {result.id for result in results}

    history, _ = search_index(
        config,
        "payment",
        mode="fts",
        include_superseded=True,
        db_path=db,
        limit=10,
    )
    assert "old" in {result.id for result in history}


def test_keyword_index_works_without_embeddings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EMU_MEM_DISABLE_EMBEDDINGS", "1")
    vault_path = tmp_path / "vault"
    write_record(vault_path, _record("one", "Idempotency key decision"))
    config = AppConfig(
        "a",
        "A",
        "d",
        default_vault="team",
        vaults={"team": VaultConfig("team", "url", vault_path, "team")},
    )
    db = tmp_path / "index.db"
    rebuild_index(config, db_path=db)
    results, _ = search_index(config, "idempotency", mode="fts", db_path=db)
    assert [item.id for item in results] == ["one"]


def test_unchanged_index_reuses_embedding(tmp_path: Path) -> None:
    vault_path = tmp_path / "vault"
    write_record(vault_path, _record("one", "Payment decision"))
    config = AppConfig(
        "a",
        "A",
        "d",
        default_vault="team",
        embed_dim=4,
        vaults={"team": VaultConfig("team", "url", vault_path, "team")},
    )
    db = tmp_path / "index.db"
    calls = 0

    def counting_embed(texts: list[str]) -> list[list[float]]:
        nonlocal calls
        calls += 1
        return _embed(texts)

    rebuild_index(config, db_path=db, embedder=counting_embed)
    rebuild_index(config, db_path=db, embedder=counting_embed)
    assert calls == 1
