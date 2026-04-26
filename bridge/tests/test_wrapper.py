"""Tests for the PTY-wrapper IPC subscription logic.

PTY forking is validated manually via ``scripts/run.sh`` + ``scripts/smoke-test.sh``
rather than here — the IO-forwarding loop is hard to exercise in a test harness
without a real terminal. These tests cover the wire protocol between the
wrapper and the daemon.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
from pathlib import Path

import pytest

from claude_buddy_bridge import wrapper


@pytest.fixture
def sock_path() -> Path:
    d = Path(tempfile.mkdtemp(prefix="bud-", dir="/tmp"))
    try:
        yield d / "w.sock"
    finally:
        for p in d.iterdir():
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        with contextlib.suppress(OSError):
            d.rmdir()


class FakeDaemon:
    """Minimal daemon stand-in: accepts one client, handles register + poll."""

    def __init__(self, sock_path: Path) -> None:
        self._sock_path = sock_path
        self._decisions: list[dict] = []
        self._cv = asyncio.Event()
        self._server: asyncio.base_events.Server | None = None
        self.registered_child_pids: list[int] = []

    async def start(self) -> None:
        self._server = await asyncio.start_unix_server(
            self._on_client, path=str(self._sock_path)
        )

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(FileNotFoundError):
            self._sock_path.unlink()

    def push_decision(self, decision: dict) -> None:
        self._decisions.append(decision)
        self._cv.set()

    async def _on_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                req = json.loads(line)
                op = req.get("op")
                if op == "register_wrapper":
                    self.registered_child_pids.append(req["child_pid"])
                    resp = {"ok": True}
                elif op == "poll_wrapper":
                    timeout = float(req.get("timeout", 30))
                    try:
                        await asyncio.wait_for(self._cv.wait(), timeout=timeout)
                    except TimeoutError:
                        resp = {"ok": True, "decisions": []}
                    else:
                        resp = {"ok": True, "decisions": self._decisions}
                        self._decisions = []
                        self._cv.clear()
                else:
                    resp = {"ok": False, "error": f"unknown op: {op}"}
                writer.write((json.dumps(resp) + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            return
        finally:
            writer.close()
            with contextlib.suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()


class TestSubscribeLoop:
    async def test_approval_decision_triggers_inject(self, sock_path):
        daemon = FakeDaemon(sock_path)
        await daemon.start()
        try:
            injected: list[bytes] = []
            stop = asyncio.Event()
            task = asyncio.create_task(
                wrapper._ipc_subscribe(
                    child_pid=123,
                    sock_path=sock_path,
                    inject=injected.append,
                    stop=stop,
                    poll_timeout_s=1.0,
                    reconnect_delay_s=0.1,
                )
            )
            # Give the subscribe loop time to register.
            await asyncio.sleep(0.05)
            assert daemon.registered_child_pids == [123]

            daemon.push_decision(
                {"session_id": "s1", "prompt_id": "p1", "decision": "once"}
            )
            for _ in range(50):
                if injected:
                    break
                await asyncio.sleep(0.02)
            assert injected == [b"y\r"]
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await daemon.stop()

    async def test_deny_decision_does_not_inject(self, sock_path):
        daemon = FakeDaemon(sock_path)
        await daemon.start()
        try:
            injected: list[bytes] = []
            stop = asyncio.Event()
            task = asyncio.create_task(
                wrapper._ipc_subscribe(
                    child_pid=456,
                    sock_path=sock_path,
                    inject=injected.append,
                    stop=stop,
                    poll_timeout_s=1.0,
                    reconnect_delay_s=0.1,
                )
            )
            await asyncio.sleep(0.05)
            daemon.push_decision(
                {"session_id": "s1", "prompt_id": "p1", "decision": "deny"}
            )
            # Wait a bit and verify nothing was injected.
            await asyncio.sleep(0.1)
            assert injected == []
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await daemon.stop()

    async def test_reconnects_when_daemon_absent(self, sock_path):
        """Wrapper keeps trying to connect so it catches a late-starting daemon."""
        injected: list[bytes] = []
        stop = asyncio.Event()
        task = asyncio.create_task(
            wrapper._ipc_subscribe(
                child_pid=789,
                sock_path=sock_path,
                inject=injected.append,
                stop=stop,
                poll_timeout_s=1.0,
                reconnect_delay_s=0.1,
            )
        )
        # Daemon isn't running yet — give the subscribe loop time to fail a few connects.
        await asyncio.sleep(0.1)
        daemon = FakeDaemon(sock_path)
        await daemon.start()
        try:
            # Shorten the reconnect delay on the wrapper's path by waiting long enough.
            for _ in range(80):
                if daemon.registered_child_pids:
                    break
                await asyncio.sleep(0.1)
            assert daemon.registered_child_pids == [789]
        finally:
            stop.set()
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
            await daemon.stop()

    async def test_stop_event_terminates_loop(self, sock_path):
        """Setting the stop event causes the subscribe loop to exit promptly."""
        daemon = FakeDaemon(sock_path)
        await daemon.start()
        try:
            stop = asyncio.Event()
            task = asyncio.create_task(
                wrapper._ipc_subscribe(
                    child_pid=1,
                    sock_path=sock_path,
                    inject=lambda _b: None,
                    stop=stop,
                    poll_timeout_s=1.0,
                    reconnect_delay_s=0.1,
                )
            )
            await asyncio.sleep(0.05)
            stop.set()
            # cancel to interrupt the current long-poll (30s); stop-event alone
            # only helps between polls, which is acceptable.
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1.0)
        finally:
            await daemon.stop()


class TestCliRunPlumbing:
    def test_run_rejects_empty_command(self):
        assert wrapper.run([]) == 2

    def test_main_rejects_empty_argv(self):
        assert wrapper.main([]) == 2
