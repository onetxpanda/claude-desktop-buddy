"""Cross-session state tracked by the daemon and projected into heartbeats."""

from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass

from .protocol import Decision, Heartbeat, Prompt


@dataclass
class _Session:
    waiting: bool = False
    pid: int | None = None
    tmux_pane: str | None = None


@dataclass(frozen=True)
class ResolvedPrompt:
    """Routing info for a buddy decision: where to send the synthetic keystroke."""

    session_id: str
    pid: int | None
    tmux_pane: str | None


@dataclass
class _PendingPrompt:
    id: str
    session_id: str
    tool: str
    hint: str
    created_at: float


class StateManager:
    """Aggregates cross-session state projected into the buddy heartbeat.

    The manager is synchronous; callers (daemon IPC handlers, BLE dispatcher)
    are expected to serialize access via the asyncio event loop.
    """

    def __init__(
        self,
        *,
        max_entries: int = 10,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._now = now
        self._sessions: dict[str, _Session] = {}
        self._pending: OrderedDict[str, _PendingPrompt] = OrderedDict()
        self._entries: deque[str] = deque(maxlen=max_entries)
        self._tokens: int = 0
        self._tokens_today: int = 0

    # --- hook-driven events ------------------------------------------------

    def _ensure_session(
        self,
        session_id: str,
        pid: int | None,
        tmux_pane: str | None = None,
    ) -> _Session:
        sess = self._sessions.get(session_id)
        if sess is None:
            sess = _Session(pid=pid, tmux_pane=tmux_pane)
            self._sessions[session_id] = sess
            return sess
        if sess.pid is None and pid is not None:
            sess.pid = pid
        if sess.tmux_pane is None and tmux_pane:
            sess.tmux_pane = tmux_pane
        return sess

    def session_start(
        self,
        session_id: str,
        pid: int | None = None,
        *,
        tmux_pane: str | None = None,
    ) -> None:
        self._ensure_session(session_id, pid, tmux_pane)

    def session_end(self, session_id: str) -> int | None:
        """Remove `session_id` and its pending prompts. Returns its tracked PID if any."""
        sess = self._sessions.pop(session_id, None)
        if sess is None:
            return None
        stale = [prompt_id for prompt_id, p in self._pending.items() if p.session_id == session_id]
        for prompt_id in stale:
            del self._pending[prompt_id]
        return sess.pid

    def pre_tool_use(
        self,
        session_id: str,
        *,
        prompt_id: str,
        tool: str,
        hint: str,
        pid: int | None = None,
        tmux_pane: str | None = None,
    ) -> None:
        self._ensure_session(session_id, pid, tmux_pane).waiting = True
        self._pending[prompt_id] = _PendingPrompt(
            id=prompt_id,
            session_id=session_id,
            tool=tool,
            hint=hint,
            created_at=self._now(),
        )
        self._push_entry(f"{self._hhmm()} {tool}: {hint}".rstrip(": ").rstrip())

    def post_tool_use(self, session_id: str, *, tool: str) -> None:
        sess = self._sessions.get(session_id)
        if sess is not None:
            sess.waiting = False
        stale = [prompt_id for prompt_id, p in self._pending.items() if p.session_id == session_id]
        for prompt_id in stale:
            del self._pending[prompt_id]

    def user_prompt_submit(
        self,
        session_id: str,
        text: str,
        *,
        pid: int | None = None,
        tmux_pane: str | None = None,
    ) -> None:
        self._ensure_session(session_id, pid, tmux_pane)
        snippet = text.strip().splitlines()[0] if text.strip() else ""
        if snippet:
            self._push_entry(f"{self._hhmm()} > {snippet[:60]}")

    def stop(
        self,
        session_id: str,
        *,
        tokens_delta: int = 0,
        pid: int | None = None,
        tmux_pane: str | None = None,
    ) -> None:
        sess = self._ensure_session(session_id, pid, tmux_pane)
        sess.waiting = False
        if tokens_delta > 0:
            self._tokens += tokens_delta
            self._tokens_today += tokens_delta

    def post_tool_use_pid(
        self,
        session_id: str,
        pid: int | None = None,
        *,
        tmux_pane: str | None = None,
    ) -> None:
        """Register PID/pane on PostToolUse without changing waiting state semantics."""
        if pid is not None or tmux_pane:
            self._ensure_session(session_id, pid, tmux_pane)

    def sessions_with_pid(self) -> list[tuple[str, int]]:
        return [
            (sid, sess.pid)
            for sid, sess in self._sessions.items()
            if sess.pid is not None
        ]

    # --- device-driven events ---------------------------------------------

    def resolve_permission(
        self, prompt_id: str, decision: Decision
    ) -> ResolvedPrompt | None:
        """Resolve a pending prompt. Returns routing info for the wrapper/tmux backend."""
        prompt = self._pending.pop(prompt_id, None)
        if prompt is None:
            return None
        sess = self._sessions.get(prompt.session_id)
        if sess is not None and not self._session_has_pending(prompt.session_id):
            sess.waiting = False
        verdict = "approved" if decision == "once" else "denied"
        self._push_entry(f"{self._hhmm()} {verdict}: {prompt.tool}")
        return ResolvedPrompt(
            session_id=prompt.session_id,
            pid=sess.pid if sess is not None else None,
            tmux_pane=sess.tmux_pane if sess is not None else None,
        )

    # --- projection --------------------------------------------------------

    def snapshot(self) -> Heartbeat:
        oldest = next(iter(self._pending.values()), None)
        prompt = (
            Prompt(id=oldest.id, tool=oldest.tool, hint=oldest.hint)
            if oldest is not None
            else None
        )
        waiting = sum(1 for s in self._sessions.values() if s.waiting)
        running = len(self._sessions) - waiting
        if prompt is not None:
            msg = f"approve: {prompt.tool}"
        elif self._entries:
            msg = self._entries[0][:40]
        else:
            msg = ""
        return Heartbeat(
            total=len(self._sessions),
            running=running,
            waiting=waiting,
            msg=msg,
            entries=list(self._entries),
            tokens=self._tokens,
            tokens_today=self._tokens_today,
            prompt=prompt,
        )

    # --- helpers -----------------------------------------------------------

    def _session_has_pending(self, session_id: str) -> bool:
        return any(p.session_id == session_id for p in self._pending.values())

    def _push_entry(self, entry: str) -> None:
        self._entries.appendleft(entry)

    def _hhmm(self) -> str:
        lt = time.localtime(self._now())
        return f"{lt.tm_hour:02d}:{lt.tm_min:02d}"
