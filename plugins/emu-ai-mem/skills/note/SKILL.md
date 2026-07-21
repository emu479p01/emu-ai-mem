---
name: note
description: Save a user-selected durable fact, decision, constraint, or handoff to emu-ai-mem. Use when the user explicitly says note this, remember this, save this to memory, or invokes the note skill.
---

# Note to emu-ai-mem

1. Extract only the durable content the user selected; never include the raw transcript or secrets.
2. Use `remember_memory` with the requested vault, project, kind, tags, and optional workspace.
3. Omit `vault` only when a deliberate default exists. Never guess a team vault.
4. Report the returned vault, memory ID, and provenance. Writes are queued locally until sync.
   If MCP is unavailable, use `emu-mem remember --summary "<text>"` with equivalent options.
