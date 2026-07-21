from __future__ import annotations

from pathlib import Path

import pytest

from emu_ai_mem.config import AppConfig, VaultConfig, load_config
from emu_ai_mem.errors import SyncError
from emu_ai_mem.gitops import clone_vault, ensure_git_identity, is_pending, run_git, sync_vault
from emu_ai_mem.records import create_record, write_record
from emu_ai_mem.services import remember
from emu_ai_mem.vaults import add_vault


def test_two_clones_rebase_unique_memories(app_home: Path, bare_remote: Path, monkeypatch) -> None:
    first = load_config()
    first.author_id = "alice"
    first.author_name = "Alice"
    first.device_id = "laptop-a"
    add_vault(first, name="team", url=str(bare_remote), kind="team", make_default=True)

    second_path = app_home.parent / "second-clone"
    clone_vault(str(bare_remote), second_path)
    ensure_git_identity(second_path, "Bob", "bob")
    second = AppConfig(
        author_id="bob",
        author_name="Bob",
        device_id="laptop-b",
        default_vault="team",
        vaults={"team": VaultConfig("team", str(bare_remote), second_path, "team")},
    )

    remember(first, project="p", tags=[], summary="Alice note", details="", category="sessions")
    record = create_record(
        second, project="p", tags=[], scope="team", summary="Bob note", details=""
    )
    path = write_record(second_path, record)
    from emu_ai_mem.gitops import commit_paths

    commit_paths(second_path, [path], f"memory: {record.id}")
    assert sync_vault("team", second_path) == "synced"
    run_git(first.vaults["team"].path, "pull", "--rebase", "origin", "main")
    files = list((first.vaults["team"].path / "memories").rglob("*.md"))
    assert len(files) == 2


def test_offline_push_leaves_pending_marker(app_home: Path, bare_remote: Path) -> None:
    config = load_config()
    add_vault(config, name="personal", url=str(bare_remote), kind="personal", make_default=True)
    path = config.vaults["personal"].path
    run_git(path, "remote", "set-url", "origin", str(bare_remote.parent / "missing.git"))
    status = sync_vault("personal", path, retries=1)
    assert status.startswith("pending:")
    assert is_pending("personal")


def test_sync_never_discards_uncommitted_changes(app_home: Path, bare_remote: Path) -> None:
    config = load_config()
    add_vault(config, name="team", url=str(bare_remote), kind="team", make_default=True)
    manifest = config.vaults["team"].path / ".emu-ai-mem.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8") + "# user edit\n", encoding="utf-8")
    with pytest.raises(SyncError, match="will not rebase or discard"):
        sync_vault("team", config.vaults["team"].path)
    assert "# user edit" in manifest.read_text(encoding="utf-8")
