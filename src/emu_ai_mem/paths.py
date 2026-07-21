from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_cache_path, user_config_path, user_data_path

APP_NAME = "emu-ai-mem"


def _override() -> Path | None:
    value = os.environ.get("EMU_MEM_HOME")
    return Path(value).expanduser().resolve() if value else None


def config_dir() -> Path:
    root = _override()
    return (root / "config") if root else Path(user_config_path(APP_NAME, appauthor=False))


def data_dir() -> Path:
    root = _override()
    return (root / "data") if root else Path(user_data_path(APP_NAME, appauthor=False))


def cache_dir() -> Path:
    root = _override()
    return (root / "cache") if root else Path(user_cache_path(APP_NAME, appauthor=False))


def ensure_app_dirs() -> None:
    for path in (
        config_dir(),
        data_dir(),
        cache_dir(),
        data_dir() / "vaults",
        cache_dir() / "locks",
    ):
        path.mkdir(parents=True, exist_ok=True)


def config_path() -> Path:
    return config_dir() / "config.toml"


def index_path() -> Path:
    return cache_dir() / "index.db"


def pending_dir() -> Path:
    path = cache_dir() / "pending"
    path.mkdir(parents=True, exist_ok=True)
    return path
