from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_claude_plugin_versions_match_python_package_version() -> None:
    package_version = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    plugin = json.loads(
        (
            ROOT
            / "claude-plugins"
            / "emu-ai-mem"
            / ".claude-plugin"
            / "plugin.json"
        ).read_text(encoding="utf-8")
    )

    marketplace_plugin = next(
        item for item in marketplace["plugins"] if item["name"] == "emu-ai-mem"
    )
    assert marketplace_plugin["version"] == package_version
    assert plugin["version"] == package_version
