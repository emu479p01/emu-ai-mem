# Plugin installation

Install the CLI first:

```bash
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v0.2.0"
emu-mem doctor
```

## Codex

Add this repository as a Codex marketplace, install `emu-ai-mem`, then start a new task
and review/trust the plugin hooks when prompted:

```bash
codex plugin marketplace add emu479p01/emu-ai-mem
codex plugin add emu-ai-mem@emu-ai-mem
```

## Claude Code

```text
/plugin marketplace add emu479p01/emu-ai-mem
/plugin install emu-ai-mem@emu-ai-mem
/reload-plugins
```

When a new release changes the plugin, bump the version in `pyproject.toml`,
`.claude-plugin/marketplace.json`, and `claude-plugins/emu-ai-mem/.claude-plugin/plugin.json`
to the same value, then push the commit and tag it. On an existing installation, refresh and
update the plugin explicitly:

```text
/plugin marketplace update emu-ai-mem
/plugin update emu-ai-mem@emu-ai-mem
```

`/reload-plugins` reloads the current cached plugin; it does not fetch a new marketplace
version. Claude Code uses the plugin version as its cache key, so pushing new commits without
changing the version does not trigger an update.

Plugins run `emu-mem hook` from PATH. `SessionStart` syncs configured vaults and
rebuilds the local index. `UserPromptSubmit` retrieves up to three relevant summaries.
`PreCompact` and `Stop` only remind the agent to persist durable context; they do not
save raw transcripts.

Both plugins also start the bundled local stdio MCP server with `emu-mem mcp`. Ask the agent to
"note this" or invoke `/emu-ai-mem:note` to call `note_memory`. MCP access uses the user-level
emu-ai-mem configuration and is independent of the current project folder.

## Claude Desktop normal chat

Install an absolute-path MCP entry in the per-user Claude Desktop configuration:

```bash
emu-mem install claude-desktop
```

Restart Claude Desktop, open Settings > Connectors, and enable `emu-ai-mem`. Then ask:

```text
Note this in my personal memory: future releases use AGPL v3; existing MIT releases remain MIT.
```

Claude should request approval for the `note_memory` write tool and report the vault, memory ID,
and sync status. This local connector works only on the computer where the CLI and vaults are
configured. It is not available to claude.ai web, Cowork, remote sessions, or mobile clients.

## Other agents

```bash
emu-mem install generic --project /path/to/project
```

Reference the generated `.emu-ai-mem/AGENT_INSTRUCTIONS.md` from that agent's durable
project guidance.
