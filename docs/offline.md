# Offline and air-gapped operation

The local SQLite store, FTS search, remember, and checkpoint operations work without a network.
Writes remain in the transactional outbox until `emu-mem sync` can export and push them.

For an air-gapped environment, use a reachable internal bare Git repository rather than GitHub.
The local engine works normally, but ChatGPT/Claude cloud surfaces and the GitHub-backed gateway
are unavailable. Transfer a wheel and its locked dependencies through the organization's approved
artifact process; do not copy a developer's home directory, OAuth store, or SQLite database.

Never clear pending markers, rewrite event segments, or reset vault history to recover from an
outage. Restore connectivity, inspect `emu-mem doctor`, and rerun sync.
