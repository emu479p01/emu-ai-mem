from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

from .config import AppConfig, VaultConfig, new_vault_path, save_config
from .errors import ConfigurationError, VaultError
from .gitops import clone_vault, commit_paths, ensure_git_identity, sync_vault

VAULT_MANIFEST = ".emu-ai-mem.toml"


def validate_vault_name(name: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,62}", name):
        raise VaultError(
            "Vault name must be 1-63 lowercase letters, digits, dot, dash, or underscore"
        )
    return name


def manifest_text(name: str, kind: str) -> str:
    return f'schema_version = 1\nname = "{name}"\nkind = "{kind}"\ndefault_branch = "main"\n'


def read_manifest(path: Path) -> dict[str, object]:
    manifest = path / VAULT_MANIFEST
    if not manifest.exists():
        raise VaultError(f"Missing {VAULT_MANIFEST} in {path}")
    try:
        raw = tomllib.loads(manifest.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise VaultError(f"Invalid vault manifest: {exc}") from exc
    if raw.get("schema_version") != 1 or raw.get("kind") not in {"personal", "team"}:
        raise VaultError("Unsupported vault schema or kind")
    return raw


def add_vault(
    config: AppConfig,
    *,
    name: str,
    url: str,
    kind: str,
    make_default: bool = False,
) -> VaultConfig:
    validate_vault_name(name)
    if kind not in {"personal", "team"}:
        raise VaultError("Vault kind must be personal or team")
    if name in config.vaults:
        raise VaultError(f"Vault {name!r} is already configured")
    destination = new_vault_path(name)
    clone_vault(url, destination)
    ensure_git_identity(destination, config.author_name, config.author_id)
    manifest = destination / VAULT_MANIFEST
    try:
        if manifest.exists():
            existing = read_manifest(destination)
            if existing["kind"] != kind:
                raise VaultError(
                    f"Vault manifest says kind={existing['kind']!r}, not requested kind={kind!r}"
                )
        else:
            manifest.write_text(manifest_text(name, kind), encoding="utf-8")
            for category in ("projects", "sessions", "decisions"):
                directory = destination / "memories" / category
                directory.mkdir(parents=True, exist_ok=True)
                keep = directory / ".gitkeep"
                keep.write_text("", encoding="utf-8")
            paths = [manifest, *sorted((destination / "memories").rglob(".gitkeep"))]
            commit_paths(destination, paths, "Initialize emu-ai-mem vault")
            result = sync_vault(name, destination)
            if result.startswith("pending"):
                raise VaultError(f"Vault initialized locally but initial push is pending: {result}")
    except Exception:
        # Keep a clone with commits for recovery, but don't register a half-configured vault.
        raise

    vault = VaultConfig(name=name, url=url, path=destination, kind=kind)
    config.vaults[name] = vault
    if make_default or config.default_vault is None:
        config.default_vault = name
    save_config(config)
    return vault


def remove_vault(config: AppConfig, name: str, *, delete_clone: bool = False) -> Path:
    try:
        vault = config.vaults.pop(name)
    except KeyError as exc:
        raise VaultError(f"Unknown vault: {name}") from exc
    if config.default_vault == name:
        config.default_vault = None
    save_config(config)
    if delete_clone and vault.path.exists():
        shutil.rmtree(vault.path)
    return vault.path


def set_default(config: AppConfig, name: str) -> None:
    if name not in config.vaults:
        raise ConfigurationError(f"Unknown vault: {name}")
    config.default_vault = name
    save_config(config)


def resolve_vault(config: AppConfig, name: str | None = None) -> VaultConfig:
    selected = name or config.default_vault
    if not selected:
        raise ConfigurationError(
            "No default vault is configured. Run `emu-mem vault set-default <name>` or pass --vault."
        )
    try:
        return config.vaults[selected]
    except KeyError as exc:
        raise ConfigurationError(f"Unknown vault: {selected}") from exc
