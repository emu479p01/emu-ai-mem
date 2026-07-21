---
name: memory
description: Search, note, sync, or supersede durable memory in configured emu-ai-mem personal and team vaults through MCP or CLI. Use before unfamiliar work, when the user says note or remember this, and at decision or handoff checkpoints.
---

# emu-ai-mem workflow

1. Before unfamiliar work, use `search_memory`; fall back to `emu-mem search "<topic>"` and cite
   the vault and memory ID for context you use.
2. When the user explicitly says note, remember, or save this, use `note_memory`; fall back to
   `emu-mem note "<text>"`. Save only durable facts, decisions, constraints, or concise handoffs.
   Never store raw transcripts, credentials, or speculative conclusions.
3. Writes go to the configured default vault. Pass `--vault <name>` when the intended sharing
   boundary differs. If no default exists, stop and ask the user to choose one.
4. Never edit a synced memory file. Use `supersede_memory` or `emu-mem supersede <id> ...`.
5. Run `emu-mem doctor` when the CLI, vault, index, or Git sync is unhealthy. A pending push is
   recoverable; do not discard the local commit.
