# emu-ai-mem v2

Session-first, local-first memory for AI agents. SQLite provides fast local resume and
incremental FTS search; immutable event segments in private GitHub repositories provide
multi-device/team replication and recovery. The SQLite database is never committed.

## What changed in v2

- Sessions and bounded checkpoints are real entities, not Markdown categories.
- Search never rebuilds an index or scans vault files on the hot path.
- Session start loads at most one 600-token continuation capsule.
- Prompt-by-prompt automatic search was removed.
- Automatic checkpoints always use a personal vault. Team handoffs are explicit.
- Local stdio MCP and a self-hosted OAuth remote MCP gateway expose the same core tools.
- v1 Markdown is read-only migration input; v2 writes immutable JSONL events.

## Install

Choose the operating-system guide:

- [Windows](docs/install/windows.md)
- [macOS](docs/install/macos.md)
- [Linux](docs/install/linux.md)

After installing the tagged release, run:

```text
emu-mem setup --check
emu-mem setup
```

The wizard reports prerequisites and next actions without guessing a vault or trusting hooks
on your behalf. See the [quick start](docs/quickstart.md), [surface matrix](docs/surfaces.md),
[team guide](docs/team-installation-guide.md), and [gateway guide](docs/gateway.md).

## Daily use

```text
emu-mem remember --vault personal --project billing --kind decision \
  --summary "Use idempotency keys for charge creation"
emu-mem search "duplicate charges"
emu-mem session latest
emu-mem sync
```

Plugins use `SessionStart`, `PreCompact`, and `Stop` hooks to resume/checkpoint where the
client exposes lifecycle metadata. They never parse raw transcripts. Cloud Chat/Work/Cowork
surfaces use the optional self-hosted gateway.

## Vault and security model

Use a different private GitHub repository for every access boundary. A personal checkpoint
is never silently copied into a team vault. `publish-handoff` creates a new sanitized team
event with checkpoint provenance.

Local state, SQLite, model caches, OAuth tokens, vault clones, and pending markers live in
platform user directories and must not be committed to this Engine repository. The gateway
encrypts GitHub tokens with an operator-provided key and rejects public vault repositories.

## Development

```text
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src/emu_ai_mem
python -m build
```

Semantic search is optional: install `emu-ai-mem[semantic]`. Gateway deployments install
`emu-ai-mem[gateway]`.

Licensed under the MIT License.
