# Supported AI surfaces

This matrix follows the current vendor contracts for
[ChatGPT plugins](https://help.openai.com/en/articles/20001256-plugins-in-codexOpenAI),
[ChatGPT Chat, Work, and Codex](https://help.openai.com/en/articles/20001275-chatgpt-work-and-codex),
[Claude remote MCP connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp), and
[Claude plugins](https://support.claude.com/en/articles/13837440-use-plugins-in-claude).

“Core tools” means search, remember, supersede, publish handoff, sync, vault listing, and
diagnostics. “Automatic continuity” additionally requires stable lifecycle hooks and session IDs.

| Product surface | Connection | Core tools | Automatic continuity |
|---|---|---:|---:|
| ChatGPT Chat (web/desktop) | Self-hosted remote gateway app | Yes | Explicit/skill-driven |
| ChatGPT Work | Self-hosted remote gateway app | Yes | Not guaranteed by the current lifecycle contract |
| ChatGPT Codex desktop/CLI | Local plugin + stdio MCP | Yes | Yes |
| Claude Desktop Chat | Local stdio MCP | Yes | Explicit |
| Claude web/mobile Chat | Remote gateway connector | Yes | Explicit |
| Claude Cowork | Remote gateway + plugin | Yes | When Cowork supplies session hook metadata |
| Claude Code | Local plugin + stdio MCP | Yes | Yes |

The engine, CLI, and local database are Tier 1 on Windows, macOS, and Linux. A desktop surface
that its vendor does not distribute for an OS is marked vendor-unavailable rather than emulated.

Cloud products cannot invoke a local stdio process. They require the HTTPS gateway described in
[gateway.md](gateway.md). Availability can also depend on plan, region, rollout, and workspace
administrator policy.

The compatibility claims follow the current vendor documentation for ChatGPT plugins and
Chat/Work/Codex, and Claude remote connectors/plugins. Recheck those documents before each release
because these surfaces evolve independently of emu-ai-mem.
