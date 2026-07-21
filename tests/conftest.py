from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def app_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "emu-home"
    monkeypatch.setenv("EMU_MEM_HOME", str(home))
    monkeypatch.setenv("EMU_MEM_DISABLE_EMBEDDINGS", "1")
    return home


@pytest.fixture
def bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    return remote
