# Install on macOS

## Supported environment

Current supported macOS on Apple Silicon or Intel, Git, and CPython 3.11/3.12 are Tier 1.

## Prerequisites and install

```bash
xcode-select --install
brew install python@3.12 git pipx
pipx ensurepath
exec "$SHELL" -l
git --version
python3.12 --version
pipx --version
ssh -T git@github.com
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v2.0.0"
emu-mem --version
emu-mem setup --check
```

For HTTPS Git, use the macOS Keychain credential helper. Credentials are handled by Git, not
emu-ai-mem. Follow [quickstart.md](../quickstart.md) for identity, personal/team vaults, and smoke
tests.

## Desktop integrations

```bash
emu-mem setup --client codex --preview
emu-mem setup --client claude-desktop --preview
```

Review the previews, rerun without `--preview`, restart the application, and manually trust Codex
hooks. Claude Desktop configuration is merged under `~/Library/Application Support/Claude/` and
backed up first.

## Upgrade and removal

Use `pipx upgrade emu-ai-mem` and then `emu-mem doctor`. Use `pipx install --force` with an older
tag to roll back code. `pipx uninstall emu-ai-mem` intentionally preserves vaults and local data.

If macOS blocks Git/SSH key access, verify `git clone` outside emu-ai-mem and review Keychain or
organization SSO. For pending sync, reconnect and rerun `emu-mem sync`.
