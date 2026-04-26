"""Incremental parser for Claude Code's JSONL transcript files.

Claude Code writes one JSON object per line to ``~/.claude/projects/<proj>/<session>.jsonl``.
Assistant turns include a ``usage`` block with ``output_tokens``; we accumulate those
to project total/today token counts into the buddy heartbeat.
"""

from __future__ import annotations

import json
from pathlib import Path


def output_tokens_from_line(line: str) -> int:
    """Return the output_tokens for an assistant-turn line, or 0 otherwise."""

    if not line:
        return 0
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return 0
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return 0
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return 0
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return 0
    value = usage.get("output_tokens", 0)
    return int(value) if isinstance(value, (int, float)) else 0


class TranscriptReader:
    """Tracks an on-disk JSONL transcript and reports new output tokens since last pull."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._offset = 0
        self._carry = ""

    def pull_delta(self) -> int:
        """Read any bytes appended since the last call and return new output tokens."""

        try:
            size = self._path.stat().st_size
        except FileNotFoundError:
            return 0

        if size < self._offset:
            self._offset = 0
            self._carry = ""

        if size == self._offset:
            return 0

        try:
            with self._path.open("rb") as f:
                f.seek(self._offset)
                chunk = f.read(size - self._offset)
        except FileNotFoundError:
            return 0

        self._offset = size
        text = self._carry + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._carry = lines[-1]
        total = 0
        for line in lines[:-1]:
            total += output_tokens_from_line(line)
        return total
