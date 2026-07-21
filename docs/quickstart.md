# v2 quick start

## Single user

1. Create an empty **private** GitHub repository for personal memory.
2. Install emu-ai-mem using the guide for your OS.
3. Configure identity and a unique device ID:

```text
emu-mem config set-identity --id alice --name "Alice Example" --device-id alice-laptop
```

4. Connect the personal vault and verify the environment:

```text
emu-mem vault add personal git@github.com:alice/personal-memory.git --kind personal --default
emu-mem setup --check
emu-mem doctor
```

5. Install the relevant client integration:

```text
emu-mem setup --client codex --preview
emu-mem setup --client claude-desktop --preview
```

Remove `--preview` after reviewing the changes. Codex still requires the user to review and
trust hooks. Claude Desktop must be restarted after its MCP configuration changes.

6. Verify the complete data path:

```text
emu-mem remember --vault personal --project onboarding --kind fact --summary "v2 is connected"
emu-mem sync --vault personal
emu-mem search "v2 connected" --vault personal
```

The search result must name the personal vault, memory ID, timestamp, and provenance.

## A second device

Install the same tagged v2 release, reuse `author_id`, choose a new `device_id`, add the same
private repository, run `emu-mem sync`, then search for the onboarding memory. Never copy the
SQLite database between devices.

## Upgrade from v1

Upgrade every device before creating v2 data. Connect the destination vault, then run:

```text
emu-mem migrate-v1 /path/to/v1-vault --vault personal
emu-mem sync --vault personal
```

Migration is hash-idempotent and does not modify source Markdown. v1 clients cannot read v2
events, so mixed writers are not supported.
