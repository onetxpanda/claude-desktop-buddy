#!/usr/bin/env bash
# End-to-end smoke test: feed fake hook events into `claude-buddy-hook` the
# same way Claude Code would, and verify the daemon's status reflects them.
#
# Run scripts/run.sh in one terminal, then run this script in another.
#
# This does NOT require BLE hardware or a real Claude Code process — it only
# exercises the hook -> IPC -> state path. If this passes, the "additive"
# surface is healthy.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

HOOK="$(pwd)/.pixi/envs/default/bin/claude-buddy-hook"
STATUS=(pixi run --quiet claude-buddy status)

if [[ ! -x "$HOOK" ]]; then
  echo "error: $HOOK not found. Run 'pixi install'." >&2
  exit 1
fi

fire() {
  # Fire one hook event. stdin is JSON as Claude Code would pass it.
  local name=$1
  local json=$2
  echo "--> $name"
  local t0 t1 ms
  t0=$(python3 -c 'import time; print(time.monotonic_ns())')
  if ! printf '%s' "$json" | "$HOOK"; then
    echo "    FAIL: hook exited non-zero"
    exit 1
  fi
  t1=$(python3 -c 'import time; print(time.monotonic_ns())')
  ms=$(( (t1 - t0) / 1000000 ))
  echo "    ok (${ms}ms)"
  if (( ms > 200 )); then
    echo "    WARN: hook took ${ms}ms — budget is 100ms"
  fi
}

status_field() {
  "${STATUS[@]}" 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(d.get('$1'))
"
}

echo "=== preflight ==="
if ! "${STATUS[@]}" >/dev/null 2>&1; then
  echo "error: daemon not reachable. Start it with: scripts/run.sh" >&2
  exit 1
fi
echo "daemon reachable."
echo

SESSION="smoke-$(date +%s)-$$"

echo "=== 1. SessionStart ==="
fire SessionStart "{\"hook_event_name\":\"SessionStart\",\"session_id\":\"$SESSION\"}"
total=$(status_field total)
echo "    daemon total=$total"
if [[ "$total" -lt 1 ]]; then
  echo "FAIL: expected total>=1, got $total"; exit 1
fi
echo

echo "=== 2. PreToolUse (Bash ls) ==="
PRETOOL_JSON=$(SESSION="$SESSION" python3 -c 'import json, os; print(json.dumps({"hook_event_name":"PreToolUse","session_id":os.environ["SESSION"],"tool_name":"Bash","tool_input":{"command":"ls -la"}}))')
fire PreToolUse "$PRETOOL_JSON"
waiting=$(status_field waiting)
prompt=$(status_field prompt)
echo "    daemon waiting=$waiting, prompt=$prompt"
if [[ "$waiting" -lt 1 ]]; then
  echo "FAIL: expected waiting>=1"; exit 1
fi
echo

echo "=== 3. PostToolUse ==="
fire PostToolUse "{\"hook_event_name\":\"PostToolUse\",\"session_id\":\"$SESSION\",\"tool_name\":\"Bash\"}"
waiting=$(status_field waiting)
echo "    daemon waiting=$waiting"
if [[ "$waiting" -ne 0 ]]; then
  echo "FAIL: expected waiting=0 after PostToolUse"; exit 1
fi
echo

echo "=== 4. SessionEnd ==="
fire SessionEnd "{\"hook_event_name\":\"SessionEnd\",\"session_id\":\"$SESSION\"}"
total=$(status_field total)
echo "    daemon total=$total"
echo

echo "=== 5. additive guarantee (hook with no daemon) ==="
echo "(no daemon check here — the hook exited 0 above on every call; shutting"
echo " down the daemon and re-running this script demonstrates the fast-fail.)"

echo
echo "SMOKE TEST PASSED"
