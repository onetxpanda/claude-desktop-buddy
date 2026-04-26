"""Claude Code hook shim.

Installed into ``~/.claude/settings.json`` as the command for every tracked
hook event. Its only job is to fire a one-shot IPC message to the bridge
daemon and exit 0. Exit code is ALWAYS 0 and stdout is ALWAYS empty so Claude
Code's behaviour is never altered.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from collections.abc import Callable
from typing import Protocol

from .ipc import IpcClient, default_socket_path

_HINT_KEYS = ("command", "file_path", "path", "pattern", "query", "url")
_HINT_MAX = 80
_TEXT_MAX = 200


class _Client(Protocol):
    async def send(self, request: dict) -> dict | None: ...


def _extract_hint(tool_name: str, tool_input: dict) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in _HINT_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str):
            return val[:_HINT_MAX]
    return ""


def _parent_pid() -> int:
    """PID of the immediate parent process.

    This is typically the Claude Code process, but depending on how Node's
    ``child_process`` launched the hook (platform- and shell-dependent) it
    may be an intermediate shell or Node worker that exits shortly after the
    hook. Treat as best-effort; ``session_id`` is the authoritative session
    identifier.
    """
    return os.getppid()


def _tmux_pane() -> str:
    """Inherited from claude → its parent shell. Empty if not running in tmux."""
    return os.environ.get("TMUX_PANE") or ""


def _build_request(payload: dict) -> dict | None:
    event = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None

    pid = _parent_pid()
    tmux_pane = _tmux_pane()

    if event == "PreToolUse":
        tool_name = str(payload.get("tool_name") or "")
        tool_input = payload.get("tool_input") or {}
        return {
            "op": "pretooluse",
            "session_id": session_id,
            "prompt_id": uuid.uuid4().hex,
            "tool": tool_name,
            "hint": _extract_hint(tool_name, tool_input),
            "pid": pid,
            "tmux_pane": tmux_pane,
        }
    if event == "PostToolUse":
        return {
            "op": "posttooluse",
            "session_id": session_id,
            "tool": str(payload.get("tool_name") or ""),
            "pid": pid,
            "tmux_pane": tmux_pane,
        }
    if event == "UserPromptSubmit":
        text = str(payload.get("prompt") or "")
        return {
            "op": "user_prompt_submit",
            "session_id": session_id,
            "text": text[:_TEXT_MAX],
            "pid": pid,
            "tmux_pane": tmux_pane,
        }
    if event == "Stop":
        tp = payload.get("transcript_path")
        return {
            "op": "stop",
            "session_id": session_id,
            "transcript_path": tp if isinstance(tp, str) else "",
            "pid": pid,
            "tmux_pane": tmux_pane,
        }
    if event == "SessionStart":
        return {
            "op": "session_start",
            "session_id": session_id,
            "pid": pid,
            "tmux_pane": tmux_pane,
        }
    if event == "SessionEnd":
        return {
            "op": "session_end",
            "session_id": session_id,
            "pid": pid,
            "tmux_pane": tmux_pane,
        }
    return None


def _default_client() -> _Client:
    return IpcClient(default_socket_path())


async def _run(*, client_factory: Callable[[], _Client] = _default_client) -> int:
    try:
        raw = sys.stdin.buffer.read()
    except Exception:
        return 0
    if not raw:
        return 0
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0

    request = _build_request(payload)
    if request is None:
        return 0

    try:
        await client_factory().send(request)
    except Exception:
        return 0
    return 0


def main() -> int:
    """Entry point. Always returns 0, even on catastrophic failure."""
    try:
        return asyncio.run(_run())
    except Exception:
        return 0


if __name__ == "__main__":
    sys.exit(main())
