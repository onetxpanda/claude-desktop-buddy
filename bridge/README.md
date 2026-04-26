# claude-buddy-bridge

Bridge between the [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
BLE device and the Claude Code **CLI**. The upstream project only supports the
desktop GUI apps — this fills the gap for terminal users.

## Design principle: additive only

With the daemon down, the buddy disconnected, or the user ignoring the device,
`claude` in a terminal behaves byte-for-byte identically to a system without
this package installed. The hook shim never blocks, never writes to stdout,
never returns a permission decision, and always exits 0 within ~100ms — even
if malformed JSON arrives on stdin or the daemon is absent.

## Status

Phase 1 — **observational**. The buddy shows pending prompts, running/waiting
session counts, recent tool activity, and token totals. Pressing **A/B** on the
device is recorded by the daemon but does not yet approve a pending tool call
in Claude Code; the terminal's normal y/n prompt is still how approvals happen.

Phase 2 (not yet built) will add an opt-in `claude-buddy run claude` PTY
wrapper that lets a device press inject `y\n` into the child `claude` process,
making the button a functional approval path.

## Requirements

- macOS (Apple Silicon or Intel) or Linux with BlueZ
- Python ≥ 3.11
- A buddy device running the upstream firmware
- [pixi](https://pixi.sh) for dependency management

## Install

```bash
cd /opt/source/claude-buddy-bridge
pixi install
```

This creates a `.pixi/envs/default` with all deps (including `bleak`) and
installs the package as an editable install. The following entry points land
on the pixi env's PATH:

- `claude-buddy` — the user-facing CLI
- `claude-buddy-hook` — the hook shim invoked by Claude Code
- `claude-buddy-bridge` — alias for `claude-buddy start`

## Use

```bash
# 1. Register our hook entries in ~/.claude/settings.json (idempotent, merges
#    with any existing hooks):
pixi run claude-buddy install

# 2. Start the daemon in a terminal (foreground — it logs to stdout):
pixi run claude-buddy start

# 3. In another terminal, use Claude Code as usual. The buddy will light up
#    when the daemon finds a nearby advertisement starting with "Claude".
```

To check status or diagnose problems:

```bash
pixi run claude-buddy status
pixi run claude-buddy doctor
```

To remove the hook entries:

```bash
pixi run claude-buddy uninstall
```

The `claude-buddy-hook` binary must be on Claude Code's `PATH` when it runs.
Either activate the pixi env (`eval "$(pixi shell-hook)"`) before launching
`claude`, or symlink the hook into a directory already on PATH:

```bash
ln -s /opt/source/claude-buddy-bridge/.pixi/envs/default/bin/claude-buddy-hook \
      /usr/local/bin/claude-buddy-hook
```

## Developing

```bash
pixi run test        # pytest
pixi run lint        # ruff
pixi run typecheck   # pyright
pixi run check       # all three
```

The BLE adapter (`ble.py::BleakTransport`) is exercised only against real
hardware; unit tests run against the in-memory `FakeTransport`.
