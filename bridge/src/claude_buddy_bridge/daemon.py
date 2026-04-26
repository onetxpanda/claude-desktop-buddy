"""Bridge daemon — the singleton that owns the BLE link and aggregates state."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from .ble import BleakTransport, Transport
from .ipc import IpcServer, default_socket_path
from .process_watcher import ProcessWatcher, make_process_watcher
from .protocol import (
    Ack,
    PermissionDecision,
    ProtocolError,
    TimeSync,
    decode_device_line,
)
from .state import ResolvedPrompt, StateManager
from .transcript import TranscriptReader

log = logging.getLogger(__name__)

HEARTBEAT_PERIOD_S = 10.0

TmuxRunner = Callable[[str, list[str]], Awaitable[bool]]


async def _default_tmux_runner(pane: str, keys: list[str]) -> bool:
    """Shell out to ``tmux send-keys -t <pane> <keys...>``. Returns True on success."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "tmux",
            "send-keys",
            "-t",
            pane,
            *keys,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError) as e:
        log.info("tmux send-keys not available (%s); falling back", e)
        return False
    rc = await proc.wait()
    return rc == 0


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.error("background task failed: %s", exc, exc_info=exc)


class Daemon:
    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        transport: Transport | None = None,
        heartbeat_period_s: float = HEARTBEAT_PERIOD_S,
        process_watcher: ProcessWatcher | None = None,
        tmux_runner: TmuxRunner | None = None,
    ) -> None:
        self._state = StateManager()
        self._ipc = IpcServer(
            socket_path or default_socket_path(), self._handle_ipc
        )
        self._transport = transport or BleakTransport()
        self._transcripts: dict[str, TranscriptReader] = {}
        self._stop_evt = asyncio.Event()
        self._wake = asyncio.Event()
        self._heartbeat_period = heartbeat_period_s
        self._watcher = process_watcher or make_process_watcher()
        self._watcher.set_exit_callback(self._on_pid_exit)
        self._loop: asyncio.AbstractEventLoop | None = None
        # Per-wrapper decision queues keyed by the claude child PID that the
        # wrapper spawned. Phase 2: the wrapper long-polls these queues and
        # injects "y\n" into its child's PTY when a decision arrives.
        self._wrapper_queues: dict[int, asyncio.Queue[dict]] = {}
        self._tmux_runner: TmuxRunner = tmux_runner or _default_tmux_runner

    # --- lifecycle ---------------------------------------------------------

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._transport.set_line_listener(self._on_device_line)
        self._transport.set_connection_listener(self._on_connection_change)
        await self._ipc.start()
        await self._transport.start()
        await self._watcher.start()
        try:
            await asyncio.gather(self._heartbeat_loop(), self._wait_stop())
        finally:
            await self._watcher.stop()
            await self._transport.stop()
            await self._ipc.stop()

    def shutdown(self) -> None:
        self._stop_evt.set()
        self._wake.set()

    async def _wait_stop(self) -> None:
        await self._stop_evt.wait()

    # --- heartbeat scheduler ----------------------------------------------

    async def _heartbeat_loop(self) -> None:
        while not self._stop_evt.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self._heartbeat_period)
            self._wake.clear()
            if self._stop_evt.is_set():
                return
            if self._transport.connected:
                await self._send_heartbeat()

    async def _send_heartbeat(self) -> None:
        await self._transport.send_line(self._state.snapshot().to_json_line())

    # --- session reaper (kqueue/polling driven) ---------------------------

    def _on_pid_exit(self, pid: int) -> None:
        """Fires from the process watcher when a tracked PID has exited."""
        reaped: list[str] = []
        for sid, spid in list(self._state.sessions_with_pid()):
            if spid == pid:
                log.info("session %s pid %d exited, reaping", sid, pid)
                self._state.session_end(sid)
                self._transcripts.pop(sid, None)
                reaped.append(sid)
        if reaped:
            self._wake.set()

    # --- IPC dispatch ------------------------------------------------------

    async def _handle_ipc(self, req: dict) -> dict:
        op = req.get("op")
        sid_raw = req.get("session_id")
        sid = sid_raw if isinstance(sid_raw, str) else ""
        pid_raw = req.get("pid")
        pid = pid_raw if isinstance(pid_raw, int) and pid_raw > 0 else None
        pane_raw = req.get("tmux_pane")
        pane = pane_raw if isinstance(pane_raw, str) and pane_raw else None

        if op == "session_start" and sid:
            self._state.session_start(sid, pid=pid, tmux_pane=pane)
            self._maybe_watch(pid)
        elif op == "session_end" and sid:
            removed_pid = self._state.session_end(sid)
            self._transcripts.pop(sid, None)
            if removed_pid is not None:
                self._watcher.unwatch(removed_pid)
        elif op == "pretooluse" and sid:
            self._state.pre_tool_use(
                sid,
                prompt_id=str(req.get("prompt_id", "")),
                tool=str(req.get("tool", "")),
                hint=str(req.get("hint", "")),
                pid=pid,
                tmux_pane=pane,
            )
            self._maybe_watch(pid)
        elif op == "posttooluse" and sid:
            self._state.post_tool_use(sid, tool=str(req.get("tool", "")))
            self._state.post_tool_use_pid(sid, pid=pid, tmux_pane=pane)
            self._maybe_watch(pid)
        elif op == "user_prompt_submit" and sid:
            self._state.user_prompt_submit(
                sid, str(req.get("text", "")), pid=pid, tmux_pane=pane
            )
            self._maybe_watch(pid)
        elif op == "stop" and sid:
            tokens = 0
            tp = req.get("transcript_path")
            if isinstance(tp, str) and tp:
                reader = self._transcripts.setdefault(sid, TranscriptReader(Path(tp)))
                tokens = reader.pull_delta()
            self._state.stop(sid, tokens_delta=tokens, pid=pid, tmux_pane=pane)
            self._maybe_watch(pid)
        elif op == "register_wrapper":
            cpid = req.get("child_pid")
            if not isinstance(cpid, int) or cpid <= 0:
                return {"ok": False, "error": "missing or invalid child_pid"}
            new_queue = cpid not in self._wrapper_queues
            self._wrapper_queues.setdefault(cpid, asyncio.Queue())
            if new_queue:
                log.info("wrapper registered for child_pid %d", cpid)
            return {"ok": True}
        elif op == "poll_wrapper":
            cpid = req.get("child_pid")
            if not isinstance(cpid, int) or cpid <= 0:
                return {"ok": False, "error": "missing or invalid child_pid"}
            queue = self._wrapper_queues.get(cpid)
            if queue is None:
                return {"ok": False, "error": "not registered"}
            timeout_raw = req.get("timeout", 30.0)
            timeout = (
                float(timeout_raw)
                if isinstance(timeout_raw, (int, float)) and timeout_raw > 0
                else 30.0
            )
            decisions: list[dict] = []
            try:
                first = await asyncio.wait_for(queue.get(), timeout=timeout)
                decisions.append(first)
            except TimeoutError:
                return {"ok": True, "decisions": []}
            while not queue.empty():
                with contextlib.suppress(asyncio.QueueEmpty):
                    decisions.append(queue.get_nowait())
            return {"ok": True, "decisions": decisions}
        elif op == "unregister_wrapper":
            cpid = req.get("child_pid")
            if isinstance(cpid, int):
                self._wrapper_queues.pop(cpid, None)
            return {"ok": True}
        elif op == "status":
            snap = self._state.snapshot()
            return {
                "ok": True,
                "connected": self._transport.connected,
                "total": snap.total,
                "running": snap.running,
                "waiting": snap.waiting,
                "tokens": snap.tokens,
                "tokens_today": snap.tokens_today,
                "prompt": (
                    {"id": snap.prompt.id, "tool": snap.prompt.tool, "hint": snap.prompt.hint}
                    if snap.prompt is not None
                    else None
                ),
            }
        else:
            return {"ok": False, "error": f"unknown op: {op}"}

        self._wake.set()
        return {"ok": True}

    def _maybe_watch(self, pid: int | None) -> None:
        if pid is not None:
            self._watcher.watch(pid)

    # --- device events -----------------------------------------------------

    def _on_device_line(self, line: bytes) -> None:
        try:
            msg = decode_device_line(line)
        except ProtocolError as e:
            log.warning("device line decode failed: %s", e)
            return
        if isinstance(msg, PermissionDecision):
            log.info("BLE: permission decision %s for prompt %s", msg.decision, msg.id)
            resolved = self._state.resolve_permission(msg.id, msg.decision)
            if resolved is None:
                log.info("BLE: no pending prompt with id %s (already resolved?)", msg.id)
            else:
                loop = self._loop
                if loop is not None:
                    task = loop.create_task(self._dispatch_decision(resolved, msg))
                    task.add_done_callback(_log_task_exception)
            self._wake.set()
        elif isinstance(msg, Ack):
            log.debug("unsolicited ack: %s", msg.ack)

    async def _dispatch_decision(
        self, resolved: ResolvedPrompt, msg: PermissionDecision
    ) -> None:
        """Route a buddy decision to the best available backend.

        Priority:
          1. tmux send-keys (if the session was launched in a tmux pane)
          2. wrapper queue (if `claude-buddy run claude` was used)
          3. nothing — Claude Code's normal terminal prompt remains in charge
        """
        if msg.decision != "once":
            # Denials aren't auto-injected — the user can type 'n' themselves.
            log.info(
                "decision %s for session %s: not auto-injecting deny",
                msg.decision,
                resolved.session_id,
            )
            return

        if resolved.tmux_pane:
            log.info(
                "tmux: send-keys 'y Enter' to pane %s for session %s",
                resolved.tmux_pane,
                resolved.session_id,
            )
            ok = await self._tmux_runner(resolved.tmux_pane, ["y", "Enter"])
            if ok:
                return
            log.warning(
                "tmux: send-keys to pane %s failed, falling back to wrapper",
                resolved.tmux_pane,
            )

        if resolved.pid is None:
            log.info(
                "decision for session %s: no pid tracked, cannot route to wrapper",
                resolved.session_id,
            )
            return

        queue = self._wrapper_queues.get(resolved.pid)
        if queue is None:
            log.info(
                "decision for session %s pid %d: no tmux pane and no wrapper "
                "registered; ignoring (Claude Code's terminal prompt is still in "
                "charge). registered wrappers: %s",
                resolved.session_id,
                resolved.pid,
                sorted(self._wrapper_queues.keys()),
            )
            return

        log.info(
            "decision once pushed to wrapper for session %s pid %d",
            resolved.session_id,
            resolved.pid,
        )
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(
                {
                    "session_id": resolved.session_id,
                    "prompt_id": msg.id,
                    "decision": msg.decision,
                }
            )

    def _on_connection_change(self, connected: bool) -> None:
        if not connected:
            return
        loop = self._loop
        if loop is None:
            return
        task = loop.create_task(self._on_connect_init())
        task.add_done_callback(_log_task_exception)

    async def _on_connect_init(self) -> None:
        now = time.time()
        tz_offset = -time.altzone if time.daylight else -time.timezone
        ts = TimeSync(epoch=int(now), tz_offset_seconds=tz_offset)
        await self._transport.send_line(ts.to_json_line())
        await self._send_heartbeat()


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("CLAUDE_BUDDY_LOG", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = Daemon()

    async def _run() -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, daemon.shutdown)
        await daemon.run()

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
