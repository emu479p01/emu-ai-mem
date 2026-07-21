# Plugin installation

Install the CLI first:

```bash
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v0.1.0"
emu-mem doctor
```

## Codex

Add this repository as a Codex marketplace, install `emu-ai-mem`, then start a new task
and review/trust the plugin hooks when prompted:

```bash
codex plugin marketplace add https://github.com/emu479p01/emu-ai-mem
codex plugin add emu-ai-mem@emu-ai-mem
```

## Claude Code

```text
/plugin marketplace add emu479p01/emu-ai-mem
/plugin install emu-ai-mem@emu-ai-mem
/reload-plugins
```

Plugins run `emu-mem hook` from PATH. `SessionStart` syncs configured vaults and
rebuilds the local index. `UserPromptSubmit` retrieves up to three relevant summaries.
`PreCompact` and `Stop` only remind the agent to persist durable context; they do not
save raw transcripts.

## Other agents

```bash
emu-mem install generic --project /path/to/project
```

Reference the generated `.emu-ai-mem/AGENT_INSTRUCTIONS.md` from that agent's durable
project guidance.

