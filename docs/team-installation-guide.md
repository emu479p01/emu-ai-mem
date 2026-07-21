# Team installation and administration

## Access boundaries

Create one empty **private** GitHub repository per group of people allowed to read the same data.
Projects and folders organize data but do not enforce access. Every person should also have a
separate personal repository for automatic checkpoints.

## Team owner

1. Create the private repository and grant the GitHub team read/write permission.
2. Install v2 using the appropriate OS guide.
3. Configure a stable person ID and unique device ID.
4. Connect personal and team vaults:

```text
emu-mem vault add personal <PERSONAL-PRIVATE-REPO> --kind personal --default
emu-mem vault add accounting-team <TEAM-PRIVATE-REPO> --kind team
emu-mem doctor
```

5. Create, sync, and search a harmless test fact:

```text
emu-mem remember --vault accounting-team --project onboarding --kind fact \
  --summary "Accounting team memory v2 is ready"
emu-mem sync --vault accounting-team
emu-mem search "team memory ready" --vault accounting-team
```

Confirm an immutable file appears under `events/v2/` in GitHub. No `.db`, OAuth token, transcript,
or generated index may appear in the repository.

## Team member and additional devices

The owner grants repository permission first. Each member installs the same v2 tag, uses one stable
`author_id`, chooses a unique `device_id` per device, and adds only authorized vaults. Verify with:

```text
emu-mem sync --vault accounting-team
emu-mem search "team memory ready" --vault accounting-team
emu-mem doctor
```

Never copy another device's config, SQLite, gateway credentials, or clone. Git events are the
portable recovery and replication format.

## Handoffs and privacy

Automatic checkpoints always go to the personal vault. Publish a deliberate team handoff with:

```text
emu-mem publish-handoff <checkpoint-id> --team-vault accounting-team --project invoice-automation
emu-mem sync --vault accounting-team
```

Review the capsule before publishing. It can contain file names, decisions, validation results,
blockers, and next steps, but never a transcript or credential.

## Self-hosted gateway administration

Follow [gateway.md](gateway.md). Use a GitHub OAuth app dedicated to one deployment, an allowlist
for pilots, HTTPS, encrypted persistent storage, least-privilege repository selection, and regular
backups. Business/Enterprise workspace owners may also need to approve the custom MCP app or
connector and its write actions.

## Upgrade and mixed-version policy

Upgrade all devices from v1 before accepting v2 writes. Run `migrate-v1`, inspect/search results,
sync, and confirm GitHub events. v2 continues importing v1 Markdown but v1 cannot read v2 events.

## Offboarding

Remove the person's GitHub repository/team permission, revoke their gateway OAuth grant, and remove
their workspace app/connector access. Existing append-only events retain authorship. Do not rewrite
Git history. The departing user removes local integrations and data according to organization policy.
