from __future__ import annotations

import subprocess
from pathlib import Path

from emu_ai_mem.config import AppConfig, VaultConfig
from emu_ai_mem.services import install_generic, migrate_legacy


def test_generic_installer(tmp_path: Path) -> None:
    path = install_generic(tmp_path)
    assert path == tmp_path / ".emu-ai-mem" / "AGENT_INSTRUCTIONS.md"
    assert "emu-mem search" in path.read_text(encoding="utf-8")


def test_migrate_legacy_without_modifying_source(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EMU_MEM_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("EMU_MEM_DISABLE_EMBEDDINGS", "1")
    source = tmp_path / "legacy" / "memories" / "decisions"
    source.mkdir(parents=True)
    old = source / "2026-07-21-old.md"
    content = """---
id: 2026-07-21-old
project: legacy
tags: [architecture]
created: 2026-07-21
---

## Summary
Old decision

## Details
Original details
"""
    old.write_text(content, encoding="utf-8")

    vault = tmp_path / "vault"
    vault.mkdir()
    subprocess.run(["git", "init"], cwd=vault, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=vault, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=vault, check=True)
    config = AppConfig(
        "chai",
        "Chai",
        "device",
        default_vault="personal",
        vaults={"personal": VaultConfig("personal", "url", vault, "personal")},
    )
    count, warnings = migrate_legacy(config, tmp_path / "legacy", auto_sync=False)
    assert count == 1
    assert not warnings
    assert old.read_text(encoding="utf-8") == content
    imported = list((vault / "memories" / "decisions").glob("*.md"))
    assert len(imported) == 1
    assert "legacy-id:2026-07-21-old" in imported[0].read_text(encoding="utf-8")
