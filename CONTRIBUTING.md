# Contributing

Thank you for helping improve emu-ai-mem.

1. Open an issue for significant behavior or schema changes.
2. Create a focused branch from `main`.
3. Install development dependencies with `python -m pip install -e ".[dev]"`.
4. Run `pytest`, `ruff check .`, `mypy src/emu_ai_mem`, and `python -m build`.
5. Do not add real memory repositories, transcripts, credentials, or generated indexes.

Memory schema changes require a migration path and compatibility tests. Git operations
must preserve local commits and must never discard unresolved user changes.

