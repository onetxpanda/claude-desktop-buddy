#!/usr/bin/env bash
# Launch the claude-buddy-bridge daemon for local testing.
#
# Usage:
#   scripts/run.sh              # start daemon with INFO logging
#   scripts/run.sh debug        # start daemon with DEBUG logging (verbose)
#
# Then in another terminal you can:
#   - check status:   pixi run claude-buddy status
#   - run doctor:     pixi run claude-buddy doctor
#   - use w/ Claude:  PATH="<BIN_DIR from banner>:$PATH" claude

set -euo pipefail

# Always run from the project root regardless of where the script was invoked.
cd "$(dirname "${BASH_SOURCE[0]}")/.."

LEVEL="${1:-INFO}"
case "$LEVEL" in
  debug|DEBUG) LEVEL=DEBUG ;;
  info|INFO)   LEVEL=INFO  ;;
  warn|WARN|warning|WARNING) LEVEL=WARNING ;;
  *)
    echo "error: unknown log level '$LEVEL' (use debug|info|warn)" >&2
    exit 2
    ;;
esac

BIN_DIR="$(pwd)/.pixi/envs/default/bin"
HOOK_BIN="$BIN_DIR/claude-buddy-hook"

if [[ ! -x "$HOOK_BIN" ]]; then
  echo "error: $HOOK_BIN not found. Run 'pixi install' first." >&2
  exit 1
fi

# Resolve the socket path the daemon will use (matches ipc.default_socket_path).
if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "$XDG_RUNTIME_DIR" ]]; then
  SOCKET="$XDG_RUNTIME_DIR/claude-buddy.sock"
else
  SOCKET="/tmp/claude-buddy-$(id -u).sock"
fi

cat <<EOF
==================== claude-buddy-bridge ====================
project dir:   $(pwd)
hook binary:   $HOOK_BIN
socket path:   $SOCKET
log level:     $LEVEL

To use with Claude Code in another terminal:
    PATH="$BIN_DIR:\$PATH" claude

Install the hook entries (idempotent; safe to re-run):
    pixi run claude-buddy install

Check status / diagnose from another terminal:
    pixi run claude-buddy status
    pixi run claude-buddy doctor

Ctrl+C to stop.
=============================================================

EOF

exec env CLAUDE_BUDDY_LOG="$LEVEL" pixi run claude-buddy start
