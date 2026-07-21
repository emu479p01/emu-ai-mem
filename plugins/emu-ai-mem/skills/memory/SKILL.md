---
name: memory
description: Search, save, sync, or supersede durable project memory in configured emu-ai-mem personal and team vaults. Use before unfamiliar work and at natural decision or handoff checkpoints.
---

# emu-ai-mem workflow

1. Before unfamiliar work, run `emu-mem search "<topic>"` and cite the vault and memory ID
   for context you use.
2. Save only durable facts, decisions, constraints, or concise session handoffs with
   `emu-mem remember`. Do not save raw transcripts, credentials, or speculative conclusions.
3. Writes go to the configured default vault. Pass `--vault <name>` when the intended sharing
   boundary differs. If no default is configured, stop and ask the user to choose one.
4. Never edit a synced memory file. Use `emu-mem supersede <id> ...` and explain what changed.
5. Run `emu-mem doctor` when the CLI, vault, index, or Git sync is unhealthy. A pending push is
   recoverable; do not discard the local commit.

