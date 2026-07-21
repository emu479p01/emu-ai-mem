# emu-ai-mem

Git-backed, multi-vault memory for AI coding agents, small teams, and one person
working across multiple machines. Markdown remains the source of truth; the local
SQLite hybrid-search index is disposable and never committed.

## Highlights

- Mount separate personal and team Git repositories without mixing access boundaries.
- Append-only memories with globally unique IDs and explicit `supersedes` history.
- Automatic fetch/rebase/push with per-vault locking, retry, and offline pending state.
- Multilingual keyword + semantic search across every mounted vault.
- Plugins for Codex and Claude Code; a generic installer for other agents.
- Local embeddings: memory content is not sent to an embedding API.

Designed for 1–20 contributors per team vault. It is not a replacement for a
central knowledge service at larger scale.

## Install

Python 3.11 or 3.12 and Git are required.

```bash
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v0.2.0"
emu-mem --version
```

Create an empty private GitHub repository for each personal or team memory vault,
then connect it. emu-ai-mem deliberately does not create repositories or manage
GitHub permissions.

```bash
emu-mem config set-identity --id emu479p01 --name "Chaiyaporn Santangjai"
emu-mem vault add personal git@github.com:YOU/my-memory.git --kind personal --default
emu-mem vault add team-acme git@github.com:ORG/team-memory.git --kind team
emu-mem doctor
```

## Use

```bash
emu-mem note "Use idempotency keys for charge creation" \
  --project billing --tags decision,api --category decisions

emu-mem remember --project billing --tags decision,api \
  --summary "Use idempotency keys for charge creation" \
  --details "Clients generate one UUID per attempted charge."

emu-mem search "how do retries avoid duplicate charges"
emu-mem search "การตัดสินใจเรื่อง payment" --vault team-acme

emu-mem supersede <old-id> --project billing --tags decision \
  --category decisions --summary "Updated retry policy" --details "..."

emu-mem sync
```

`note` is the folder-independent shortcut for content the user explicitly selected. It uses
`project=general` and `category=sessions` when those options are omitted, while still requiring an
explicitly configured default vault or `--vault`.

Writes require an explicit default vault or `--vault`. Search uses all configured
vaults by default and labels every result with its origin. Synced files are
append-only; use `supersede` rather than editing history.

## Vault format

Every memory repository contains `.emu-ai-mem.toml` and one Markdown file per entry:

```text
memory-repo/
├── .emu-ai-mem.toml
└── memories/
    ├── projects/
    ├── sessions/
    └── decisions/
```

The repository is the access-control boundary. A `personal` folder inside a team
repository would still be readable by the team, so personal and team data must use
different repositories.

## Existing ai-mem data

Connect a destination vault first, then import without modifying the source files:

```bash
emu-mem migrate /path/to/old-ai-mem --vault personal
```

Each imported record receives a v1 ID and a `legacy-id:*` tag. Verify the remote
before deleting the old files.

## Agent integrations

- Codex marketplace: `.agents/plugins/marketplace.json`
- Claude Code marketplace: `.claude-plugin/marketplace.json`
- Other agents: `emu-mem install generic --project /path/to/project`

For folder-independent access from the normal Claude Desktop chat, install the user-wide local
MCP entry and restart Claude Desktop:

```bash
emu-mem install claude-desktop
```

The local MCP server exposes `note_memory`, `search_memory`, `supersede_memory`, `sync_memory`,
`list_vaults`, and `doctor_memory`. It runs over stdio on the same computer and does not expose a
network port. Claude.ai web and mobile cannot connect to this local server.

Plugins call the installed `emu-mem` executable. They sync at session start,
retrieve relevant context for prompts, and remind the agent to save durable facts.
They never sync raw transcripts by default.

See [docs/plugins.md](docs/plugins.md) for installation details.

For complete onboarding instructions—including team owner setup, member N, device N,
multiple teams, and multiple projects—see the
[installation and team onboarding guide](docs/team-installation-guide.md).

## Development

```bash
python -m venv .venv
# activate .venv
python -m pip install -e ".[dev]"
pytest
ruff check .
mypy src/emu_ai_mem
python -m build
```

The default semantic model is
`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions).
Changing the model or dimension requires `emu-mem reindex`.

## Security and privacy

- Repository permissions are enforced by GitHub/Git, not by emu-ai-mem metadata.
- Credentials remain in the user's existing Git credential manager or SSH agent.
- Config, clones, indexes, locks, and pending markers live in platform user directories.
- Plugins may put selected memory summaries into agent context; only mount vaults whose
  content is appropriate for that agent session.

Licensed under the [MIT License](LICENSE).
