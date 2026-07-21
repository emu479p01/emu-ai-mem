# Install on Windows

## Supported environment

Windows 10/11 x64, Git, and CPython 3.11 or 3.12 are Tier 1. Use PowerShell for all commands in
this guide. Do not copy POSIX line continuations into PowerShell.

## Prerequisites

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
py -3.12 -m pip install --user pipx
py -3.12 -m pipx ensurepath
```

Close and reopen PowerShell, then verify:

```powershell
git --version
py -3.12 --version
pipx --version
ssh -T git@github.com
```

For HTTPS repositories, sign in through Git Credential Manager. emu-ai-mem never stores a
GitHub password or personal access token.

## Install and initialize

```powershell
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v2.0.0"
emu-mem --version
emu-mem setup --check
```

Expected version: `2.0.0`. Follow [quickstart.md](../quickstart.md) to create identity and vaults.

Local state defaults to `%LOCALAPPDATA%`/platformdirs locations. Run `emu-mem setup --check` and
`emu-mem doctor` to print the exact config, data, and database paths on this device.

## Desktop integrations

Preview before changing configuration:

```powershell
emu-mem setup --client codex --preview
emu-mem setup --client claude-desktop --preview
```

Then rerun without `--preview`. Existing Claude Desktop JSON is backed up and merged. Restart the
desktop application. Review/trust Codex hooks manually; the installer cannot approve them.

## Upgrade, rollback, uninstall

```powershell
pipx upgrade emu-ai-mem
emu-mem doctor
```

Rollback by forcing a known tag with `pipx install --force`. Event schema v2 remains append-only.
Uninstall the executable with `pipx uninstall emu-ai-mem`; this does not delete vault clones,
SQLite, Git history, or gateway data. Remove those only after inspecting paths from `doctor`.

## Troubleshooting

- Command missing: reopen PowerShell and run `py -3.12 -m pipx ensurepath`.
- SSH failure: repair the SSH agent/key or use Git Credential Manager with HTTPS.
- Corporate proxy/firewall: verify ordinary `git fetch` and HTTPS to GitHub first.
- Pending sync: reconnect and run `emu-mem sync --vault <name>`; never reset the vault destructively.
