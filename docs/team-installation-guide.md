# Installation and team onboarding guide

This guide covers a new installation, the first team setup, additional team members,
multiple devices per person, multiple teams, and multiple projects. It targets
emu-ai-mem v0.2.0 and teams of 1–20 people per memory repository.

## 1. Understand the layout before installing

emu-ai-mem separates the public Engine from private memory data:

```text
Public Engine repository
└── emu479p01/emu-ai-mem

Private memory repositories created by you
├── my-personal-memory           one person's private vault
├── accounting-team-memory      one team's shared vault
└── development-team-memory     another team's shared vault
```

A **vault** is one cloned memory repository. A **project** is metadata inside a
memory record. Use one shared vault for several projects when the same people may read
all of them. Create separate vaults when membership or confidentiality differs.

Repository access is the security boundary. A folder named `personal` inside a team
repository is still visible to everyone who can clone that repository.

## 2. Prerequisites on every device

Install the following on every computer that will use emu-ai-mem:

1. Git.
2. Python 3.11 or 3.12.
3. pipx.
4. GitHub authentication that can clone and push the intended private repositories.

### Windows

```powershell
python --version
git --version
python -m pip install --user pipx
python -m pipx ensurepath
```

Close and reopen PowerShell after `ensurepath`. If `python` is not available, install
Python 3.11 or 3.12 first and enable its PATH option.

### macOS or Linux

Use the operating system package manager to install Python, Git, and pipx, then verify:

```bash
python3 --version
git --version
pipx --version
```

### Verify GitHub access

For SSH repositories:

```bash
ssh -T git@github.com
```

For HTTPS repositories, sign in with Git Credential Manager or another credential
helper. emu-ai-mem uses normal `git clone`, `git fetch`, and `git push`; it does not
store GitHub tokens.

## 3. Install the Engine on every device

Install the tagged release, not the moving `main` branch:

```bash
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v0.2.0"
emu-mem --version
```

Expected output:

```text
0.2.0
```

Each device has its own local configuration, vault clones, SQLite index, model cache,
locks, and pending-push status. These are not committed to the Engine repository.

The multi-line examples below use the POSIX `\` line continuation. In PowerShell,
either put the command on one line or replace each trailing `\` with a backtick (`` ` ``).

## 4. Set the identity for person N on device N

Use the same `author_id` for one person on every device. Use a different `device_id`
for every computer.

Example for Alice's first device:

```bash
emu-mem config set-identity \
  --id alice \
  --name "Alice Example" \
  --device-id alice-office-windows
```

Example for Alice's second device:

```bash
emu-mem config set-identity \
  --id alice \
  --name "Alice Example" \
  --device-id alice-macbook
```

Example for team member N on device N:

```bash
emu-mem config set-identity \
  --id <stable-person-id> \
  --name "<person display name>" \
  --device-id <unique-person-and-device-id>
```

Check the saved identity:

```bash
emu-mem config show
```

Recommended IDs contain lowercase letters, digits, and dashes. Do not reuse one
`device_id` on two computers.

## 5. Team owner: create the first team memory repository

The team owner performs this section once per team.

1. Open GitHub and create a new repository such as `accounting-team-memory`.
2. Set visibility to **Private**.
3. Prefer a dedicated empty repository. Do not use the public Engine repository for
   private memories.
4. Grant team members Read/Write access through GitHub collaborators or an organization
   team.
5. Copy its SSH or HTTPS Git URL.

On the owner's first device, connect and initialize it:

```bash
emu-mem vault add accounting-team \
  git@github.com:YOUR-ORG/accounting-team-memory.git \
  --kind team \
  --default
```

This clones the repository, creates `.emu-ai-mem.toml` and the memory directories when
needed, commits them, and pushes `main`.

Verify the setup:

```bash
emu-mem vault list
emu-mem doctor
```

Create the first test memory:

```bash
emu-mem remember \
  --vault accounting-team \
  --project invoice-automation \
  --category decisions \
  --tags onboarding,test \
  --summary "The shared team vault is ready" \
  --details "Created during the initial team setup."
```

Confirm that the new Markdown file appears in the private GitHub repository before
onboarding other members.

## 6. Team member N: connect the first device

Before starting, the repository owner must grant this member access. On the member's
computer:

1. Complete prerequisites and install the Engine.
2. Set the member and device identity.
3. Add the same GitHub memory repository, using the same local vault name when possible.

```bash
emu-mem config set-identity \
  --id bob \
  --name "Bob Example" \
  --device-id bob-home-linux

emu-mem vault add accounting-team \
  git@github.com:YOUR-ORG/accounting-team-memory.git \
  --kind team \
  --default
```

Then verify that the first shared memory is searchable:

```bash
emu-mem sync --vault accounting-team
emu-mem search "shared team vault" --vault accounting-team
emu-mem doctor
```

The local SQLite index is rebuilt from the cloned Markdown files. It is not downloaded
from GitHub.

## 7. Person N: connect device N

Repeat these steps for every additional computer owned by any member:

1. Install Git, Python, pipx, and emu-ai-mem.
2. Authenticate Git with GitHub on that computer.
3. Reuse the person's stable `author_id` and `author_name`.
4. assign a new, unique `device_id`.
5. Add each vault that this device needs.
6. Run `sync`, `search`, and `doctor`.

Template:

```bash
emu-mem config set-identity \
  --id <same-person-id-used-on-other-devices> \
  --name "<same-display-name>" \
  --device-id <new-unique-device-id>

emu-mem vault add <local-vault-name> <team-repository-url> --kind team --default
emu-mem sync --vault <local-vault-name>
emu-mem doctor
```

Do not manually copy the local SQLite database or configuration from another device.
The Git repository is the shared source of truth; every device builds its own index.

## 8. Use multiple projects in one team

Use the same team vault with a different `--project` value when all vault members may
read every project's memories:

```bash
emu-mem remember \
  --vault accounting-team \
  --project invoice-automation \
  --tags decision,api \
  --summary "Invoice API uses idempotency keys" \
  --details "One key is generated per business transaction."

emu-mem remember \
  --vault accounting-team \
  --project tax-reporting \
  --tags requirement \
  --summary "Tax reports close on the third business day" \
  --details "Approved by the accounting team."
```

Search the team vault:

```bash
emu-mem search "invoice API" --vault accounting-team
emu-mem search "tax report close" --vault accounting-team
```

Project names organize records; they do not enforce access control.

## 9. Connect multiple teams

Create one private repository per access boundary and add each as a vault:

```bash
emu-mem vault add accounting-team <ACCOUNTING-REPO-URL> --kind team --default
emu-mem vault add sales-team <SALES-REPO-URL> --kind team
emu-mem vault add development-team <DEVELOPMENT-REPO-URL> --kind team
emu-mem vault list
```

There is one default vault per local device in v0.2.0. When several team vaults are
configured, explicitly pass `--vault` for writes to avoid sharing a memory with the
wrong team:

```bash
emu-mem remember --vault sales-team --project crm --summary "..." --details "..."
```

Search queries use all configured vaults by default and label every result with its
origin. Restrict sensitive work to the intended vault:

```bash
emu-mem search "customer retention" --vault sales-team
```

## 10. Add a personal vault

Create a separate private repository accessible only to that person, then add it:

```bash
emu-mem vault add personal <PERSONAL-REPO-URL> --kind personal
```

Choose the default according to the main use of that device:

```bash
emu-mem vault set-default personal
# or
emu-mem vault set-default accounting-team
```

Always pass `--vault personal` for information that must not be shared with a team.

## 11. Install an AI client integration

Install the CLI and configure at least one vault before installing a plugin.

### Codex

```bash
codex plugin marketplace add emu479p01/emu-ai-mem
codex plugin add emu-ai-mem@emu-ai-mem
```

Start a new Codex task and review/trust the plugin hooks when prompted.

### Claude Code

Run inside Claude Code:

```text
/plugin marketplace add emu479p01/emu-ai-mem
/plugin install emu-ai-mem@emu-ai-mem
/reload-plugins
```

### Other agents

```bash
emu-mem install generic --project /path/to/project
```

Reference `.emu-ai-mem/AGENT_INSTRUCTIONS.md` from that agent's durable project
instructions.

## 12. Normal daily workflow

At the start of work:

```bash
emu-mem sync
emu-mem search "topic being worked on" --vault <team-vault>
```

At a decision or handoff checkpoint:

```bash
emu-mem remember \
  --vault <team-vault> \
  --project <project-name> \
  --category decisions \
  --tags decision,architecture \
  --summary "Short durable conclusion" \
  --details "Reasoning, constraints, and consequences."
```

To correct a synced memory, create a replacement instead of editing history:

```bash
emu-mem supersede <old-memory-id> \
  --vault <team-vault> \
  --project <project-name> \
  --summary "Corrected conclusion" \
  --details "What changed and why."
```

## 13. Migrate data from the original ai-mem

Connect the destination vault first, then import:

```bash
emu-mem migrate /path/to/old-ai-mem --vault personal
```

Verify the imported Markdown files on GitHub before deleting the old source. Migration
does not modify the source files.

## 14. Upgrade to a later release

Replace `<VERSION>` with a published tag, for example `v0.2.0`:

```bash
pipx install --force "git+https://github.com/emu479p01/emu-ai-mem.git@<VERSION>"
emu-mem --version
emu-mem doctor
```

Run `emu-mem reindex` when release notes say the model or index format changed.

## 15. Use Claude Desktop chat without a project folder

On each Windows or macOS device that should expose its local vaults to the normal Claude Desktop
chat, run:

```bash
emu-mem install claude-desktop
```

Restart Claude Desktop, enable the `emu-ai-mem` local connector, and ask Claude to "note this".
Claude must request approval before a write tool runs. The connector uses that device's identity,
default vault, clones, and Git credentials; it does not depend on the chat's current folder.

This is local MCP. It is unavailable in claude.ai web, Cowork, remote sessions, and mobile apps.

## 16. Onboarding and offboarding checklist

### Onboarding

- Grant only the required private repositories.
- Install the tagged Engine release on each device.
- Keep one stable author ID per person and one unique device ID per computer.
- Add only the vaults appropriate for that device and role.
- Verify `sync`, `search`, and `doctor`.
- Review and trust AI-client plugin hooks before enabling them.

### Offboarding

- Remove the person or organization team from the private GitHub repositories.
- Rotate repository credentials if organizational policy requires it.
- Ask the departing member to remove local vault configurations and clones.
- Do not rewrite existing authored memories; append-only history preserves attribution.

## 17. Troubleshooting

### `emu-mem` is not found

Run `python -m pipx ensurepath`, reopen the terminal, and verify `pipx list`.

### No default vault is configured

```bash
emu-mem vault list
emu-mem vault set-default <vault-name>
```

### Git authentication fails

Test `git clone <repository-url>` or `ssh -T git@github.com` outside emu-ai-mem. Fix
the Git credential helper, SSH key, repository permission, or organization SSO access.

### Push is pending or the computer was offline

The local commit is preserved. Reconnect and run:

```bash
emu-mem sync --vault <vault-name>
emu-mem doctor
```

### The vault has uncommitted changes

emu-ai-mem will not discard or rebase over them. Open the clone path shown by
`emu-mem doctor`, inspect `git status`, and resolve the changes manually before syncing.

### First semantic search is slow

The multilingual embedding model is downloaded and initialized locally on first use.
Later searches reuse the model cache and stored embeddings. Memory content is not sent
to an embedding API.

### A memory was written to the wrong team

Do not copy sensitive content between access boundaries without authorization. Correct
the history according to team policy, then explicitly use `--vault` for subsequent
writes. The default vault is local to each device.
