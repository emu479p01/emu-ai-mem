# Plugins and client integrations

Install the v2 engine and configure a personal vault before enabling lifecycle hooks.

## Codex

Preview and install through the wizard:

```text
emu-mem setup --client codex --preview
emu-mem setup --client codex
```

The repo marketplace can also be added manually with `codex plugin marketplace add
emu479p01/emu-ai-mem`, followed by `codex plugin add emu-ai-mem@emu-ai-mem`. Start a new task and
review/trust the plugin hooks. The plugin bundles a local stdio MCP server and session lifecycle
instructions.

## Claude Code

Run the commands printed by `emu-mem setup --client claude-code` inside Claude Code, reload
plugins, and start a new session. Claude Code uses the dedicated Claude plugin bundle.

## Claude Desktop Chat

`emu-mem setup --client claude-desktop` backs up and merges
`claude_desktop_config.json`. Restart Claude Desktop and approve write tools when asked. This local
connector does not make the engine reachable from Claude web or Cowork.

## ChatGPT Chat/Work and Claude web/Cowork

Deploy the HTTPS gateway and register its `/mcp` URL as a custom app/connector. The Codex local
plugin does not embed a deployment-specific remote app ID: each self-hosted operator creates and
approves that app in its workspace, then may associate it with a private plugin listing/template.
See [gateway.md](gateway.md) and [surfaces.md](surfaces.md).

## Lifecycle behavior

Only `SessionStart`, `PreCompact`, and `Stop` are configured. There is no `UserPromptSubmit` search,
so ordinary prompts do not pay a search/model/token cost. Stop requests at most one checkpoint retry
per turn and never blocks forever.

Plugin version, Python package version, marketplace metadata, MCP tool schemas, and hook fixtures
are validated together before release.
