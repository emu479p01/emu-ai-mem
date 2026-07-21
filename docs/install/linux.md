# Install on Linux

## Supported environment

x86_64/aarch64 Linux with glibc, Git, and CPython 3.11/3.12 are Tier 1 for the engine, Codex CLI,
and Claude Code. Desktop clients depend on vendor availability.

## Debian/Ubuntu

```bash
sudo apt update
sudo apt install -y git python3.12 python3-pip pipx
pipx ensurepath
exec "$SHELL" -l
```

## Fedora

```bash
sudo dnf install -y git python3.12 pipx
pipx ensurepath
exec "$SHELL" -l
```

## Verify and install

```bash
git --version
python3 --version
pipx --version
ssh -T git@github.com
pipx install "git+https://github.com/emu479p01/emu-ai-mem.git@v2.0.0"
emu-mem --version
emu-mem setup --check
```

Follow [quickstart.md](../quickstart.md). Install Codex with `emu-mem setup --client codex` where
Codex is available. For Claude Code, the wizard prints the marketplace commands to run inside
Claude Code.

Platformdirs selects XDG config/data/cache locations; `setup --check` prints exact paths. Service
accounts must have writable XDG directories and non-interactive Git credentials.

Upgrade with `pipx upgrade emu-ai-mem`. Uninstalling pipx does not delete vaults or SQLite. If a
binary wheel for optional semantic dependencies is unavailable on the CPU, omit `[semantic]`;
FTS and session continuity remain fully functional.
