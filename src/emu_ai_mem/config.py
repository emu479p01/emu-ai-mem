from __future__ import annotations

import getpass
import os
import re
import shutil
import socket
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigurationError
from .paths import config_path, data_dir, ensure_app_dirs

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_EMBED_DIM = 384


@dataclass(slots=True)
class VaultConfig:
    name: str
    url: str
    path: Path
    kind: str


@dataclass(slots=True)
class AppConfig:
    author_id: str
    author_name: str
    device_id: str
    default_vault: str | None = None
    model: str = DEFAULT_MODEL
    embed_dim: int = DEFAULT_EMBED_DIM
    vaults: dict[str, VaultConfig] = field(default_factory=dict)


def _slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return value or "user"


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def default_config() -> AppConfig:
    username = getpass.getuser()
    host = socket.gethostname()
    return AppConfig(
        author_id=_slug(username),
        author_name=username,
        device_id=f"{_slug(host)}-{uuid.uuid4().hex[:8]}",
    )


def load_config(*, create: bool = True) -> AppConfig:
    path = config_path()
    if not path.exists():
        config = default_config()
        if create:
            ensure_app_dirs()
            save_config(config)
        return config
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        schema_version = int(raw.get("schema_version", 1))
        if schema_version not in {1, 2}:
            raise ConfigurationError(f"Unsupported config schema_version: {schema_version}")
        identity = raw["identity"]
        settings = raw.get("settings", {})
        vaults = {
            name: VaultConfig(
                name=name,
                url=value["url"],
                path=Path(value["path"]).expanduser(),
                kind=value["kind"],
            )
            for name, value in raw.get("vaults", {}).items()
        }
        return AppConfig(
            author_id=identity["author_id"],
            author_name=identity["author_name"],
            device_id=identity["device_id"],
            default_vault=settings.get("default_vault") or None,
            model=settings.get("model", DEFAULT_MODEL),
            embed_dim=int(settings.get("embed_dim", DEFAULT_EMBED_DIM)),
            vaults=vaults,
        )
    except ConfigurationError:
        raise
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise ConfigurationError(f"Invalid config file {path}: {exc}") from exc


def save_config(config: AppConfig) -> None:
    ensure_app_dirs()
    lines = [
        "schema_version = 2",
        "",
        "[identity]",
        f"author_id = {_quote(config.author_id)}",
        f"author_name = {_quote(config.author_name)}",
        f"device_id = {_quote(config.device_id)}",
        "",
        "[settings]",
        f"default_vault = {_quote(config.default_vault or '')}",
        f"model = {_quote(config.model)}",
        f"embed_dim = {config.embed_dim}",
    ]
    for name in sorted(config.vaults):
        vault = config.vaults[name]
        lines.extend(
            [
                "",
                f"[vaults.{_quote(name)}]",
                f"url = {_quote(vault.url)}",
                f"path = {_quote(str(vault.path))}",
                f"kind = {_quote(vault.kind)}",
            ]
        )
    target = config_path()
    if target.exists():
        try:
            previous = tomllib.loads(target.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            previous = {}
        if previous.get("schema_version", 1) == 1:
            backup = target.with_suffix(target.suffix + ".v1.bak")
            if not backup.exists():
                shutil.copy2(target, backup)
    tmp = target.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, target)


def new_vault_path(name: str) -> Path:
    return data_dir() / "vaults" / name
