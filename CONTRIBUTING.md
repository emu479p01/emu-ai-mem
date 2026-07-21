# Contributing

Thank you for helping improve emu-ai-mem.

1. Open an issue for significant behavior or schema changes.
2. Create a focused branch from `main`.
3. Install development dependencies with `python -m pip install -e ".[dev]"`.
4. Run `pytest`, `ruff check .`, `mypy src/emu_ai_mem`, and `python -m build`.
5. Do not add real memory repositories, transcripts, credentials, or generated indexes.

Memory schema changes require a migration path and compatibility tests. Git operations
must preserve local commits and must never discard unresolved user changes.

## Validation and release workflow

GitHub Actions deliberately does not run the cross-platform matrix for every push or
pull request. Run the relevant checks locally while developing. The `Validation`
workflow can also be started manually from the Actions page when an exceptional remote
check is needed.

For a release, update the package and plugin versions, commit the changes, and push an
annotated `v<version>` tag. The `Release` workflow calls the complete Validation workflow
on Windows, macOS, and Ubuntu with Python 3.11 and 3.12. The GitHub Release and its
wheel/sdist assets are created only after all validation jobs pass. A tag that does not
match the version in `pyproject.toml` is rejected.
