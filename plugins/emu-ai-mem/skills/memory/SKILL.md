---
name: memory
description: Resume bounded session context and search, save, sync, supersede, or publish durable emu-ai-mem records through MCP or CLI.
---

# emu-ai-mem workflow

1. Resume only with the bounded context supplied at session start or `get_session_context`.
   Do not search every prompt. Use `search_memory` on demand for unfamiliar facts and cite provenance.
2. When the user explicitly asks to save something, use `remember_memory`; fall back to
   `emu-mem remember`. Save only durable facts, decisions, constraints, or concise notes.
   Do not save raw transcripts, credentials, or speculative conclusions.
3. Writes go to the configured default vault. Pass `--vault <name>` when the intended sharing
   boundary differs. If no default is configured, stop and ask the user to choose one.
4. Never edit a synced event. Use `supersede_memory`. Publish a personal checkpoint to a team
   only with explicit `publish_handoff` authorization.
5. At checkpoint requests, call `checkpoint_session` with structured state only; never send the
   raw transcript or credentials.
6. Run `emu-mem doctor` when the CLI, database, vault, or Git sync is unhealthy. A pending push is
   recoverable; do not discard the local commit.
