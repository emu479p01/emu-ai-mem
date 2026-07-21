from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[1]


def package_version() -> str:
    text = (ROOT / "src" / "emu_ai_mem" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__ = "([^"]+)"$', text, flags=re.MULTILINE)
    if not match:
        raise SystemExit("Could not read package version")
    return match.group(1)


def main() -> None:
    expected = package_version()
    documents = [
        ROOT / "plugins" / "emu-ai-mem" / ".codex-plugin" / "plugin.json",
        ROOT / "claude-plugins" / "emu-ai-mem" / ".claude-plugin" / "plugin.json",
    ]
    versions = [json.loads(path.read_text(encoding="utf-8"))["version"] for path in documents]
    marketplace = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    versions.extend(
        item["version"] for item in marketplace["plugins"] if item["name"] == "emu-ai-mem"
    )
    if any(version != expected for version in versions):
        raise SystemExit(f"Plugin versions {versions!r} do not match package {expected}")
    print(expected)


if __name__ == "__main__":
    main()
