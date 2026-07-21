# Agent guidance

This repository contains the public emu-ai-mem Engine. Never add real memories,
transcripts, credentials, local vault clones, or generated indexes to Git.

Before changing behavior, inspect the v1 schema and the corresponding tests. Preserve
append-only semantics and never make Git recovery destructive. Run `pytest`,
`ruff check .`, and `mypy src/emu_ai_mem` before handing off changes.

