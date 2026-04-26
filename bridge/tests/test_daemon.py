from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from claude_buddy_bridge.ble import FakeTransport
from claude_buddy_bridge.daemon import Daemon
from claude_buddy_bridge.ipc import IpcClient
from claude_buddy_bridge.process_watcher import ProcessWatcher


class FakeProcessWatcher(ProcessWatcher):
    """Test double that lets us synthesize exit events."""

    def __init__(self) -> None:
        self.watched: set[int] = set()
        self._cb: Callable[[int], None] | None = None

    def set_exit_callback(self, cb: Callable[[int], None]) -> None:
        self._cb = cb

    def watch(self, pid: int) -> None:
        self.watched.add(pid)

    def unwatch(self, pid: int) -> None:
        self.watched.discard(pid)

    async def start(self) -> None: ...
    async def stop(self) -> None: ...

    def fire_exit(self, pid: int) -> None:
        self.watched.discard(pid)
        if self._cb is not None:
            self._cb(pid)


@pytest.fixture
def sock_path() -> Path:
    d = Path(tempfile.mkdtemp(prefix="bud-", dir="/tmp"))
    try:
        yield d / "d.sock"
    finally:
        for p in d.iterdir():
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        with contextlib.suppress(OSError):
            d.rmdir()


@pytest.fixture
async def running_daemon(sock_path):
    transport = FakeTransport()
    watcher = FakeProcessWatcher()
    daemon = Daemon(
        socket_path=sock_path,
        transport=transport,
        heartbeat_period_s=60.0,
        process_watcher=watcher,
        # Default tmux runner shells out to real tmux; tests don't want that.
        tmux_runner=_unused_tmux_runner,
    )
    task = asyncio.create_task(daemon.run())
    await asyncio.sleep(0.02)
    try:
        yield daemon, transport, watcher
    finally:
        daemon.shutdown()
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except TimeoutError:
            task.cancel()


async def _unused_tmux_runner(_pane: str, _keys: list[str]) -> bool:
    return False


class TestIpcDispatch:
    async def test_session_start_triggers_heartbeat_when_connected(self, running_daemon, sock_path):
        _daemon, transport, _watcher = running_daemon
        transport.simulate_connect()
        await asyncio.sleep(0.05)
        initial_count = len(transport.sent)
        assert initial_count >= 2

        client = IpcClient(sock_path, total_budget_s=1.0)
        resp = await client.send({"op": "session_start", "session_id": "s1"})
        assert resp == {"ok": True}
        await asyncio.sleep(0.05)
        assert len(transport.sent) > initial_count
        hb = json.loads(transport.sent[-1])
        assert hb["total"] == 1
        assert hb["running"] == 1

    async def test_no_heartbeat_sent_while_disconnected(self, running_daemon, sock_path):
        _daemon, transport, _watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1"})
        await asyncio.sleep(0.05)
        assert transport.sent == []

    async def test_pretooluse_produces_prompt_in_heartbeat(self, running_daemon, sock_path):
        _daemon, transport, _watcher = running_daemon
        transport.simulate_connect()
        await asyncio.sleep(0.05)

        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1"})
        await client.send(
            {
                "op": "pretooluse",
                "session_id": "s1",
                "prompt_id": "p1",
                "tool": "Bash",
                "hint": "ls",
            }
        )
        await asyncio.sleep(0.05)
        hb = json.loads(transport.sent[-1])
        assert hb["prompt"] == {"id": "p1", "tool": "Bash", "hint": "ls"}
        assert hb["waiting"] == 1

    async def test_device_decision_clears_waiting(self, running_daemon, sock_path):
        _daemon, transport, _watcher = running_daemon
        transport.simulate_connect()
        await asyncio.sleep(0.05)
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1"})
        await client.send(
            {
                "op": "pretooluse",
                "session_id": "s1",
                "prompt_id": "p1",
                "tool": "Bash",
                "hint": "ls",
            }
        )
        transport.simulate_receive(b'{"cmd":"permission","id":"p1","decision":"once"}\n')
        await asyncio.sleep(0.05)
        hb = json.loads(transport.sent[-1])
        assert hb["waiting"] == 0
        assert hb.get("prompt") is None

    async def test_status_op_returns_snapshot(self, running_daemon, sock_path):
        _daemon, _transport, _watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1"})
        resp = await client.send({"op": "status"})
        assert resp["ok"] is True
        assert resp["connected"] is False
        assert resp["total"] == 1


class TestConnectInit:
    async def test_connect_sends_time_sync_first(self, running_daemon):
        _daemon, transport, _watcher = running_daemon
        transport.simulate_connect()
        await asyncio.sleep(0.05)
        first = json.loads(transport.sent[0])
        assert "time" in first
        assert isinstance(first["time"], list)
        assert len(first["time"]) == 2


class TestUnknownOp:
    async def test_unknown_op_returns_error(self, running_daemon, sock_path):
        client = IpcClient(sock_path, total_budget_s=1.0)
        resp = await client.send({"op": "mystery"})
        assert resp["ok"] is False
        assert "unknown op" in resp["error"]


class TestProcessWatcherIntegration:
    async def test_session_start_with_pid_registers_watch(self, running_daemon, sock_path):
        _daemon, _transport, watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1", "pid": 1111})
        assert 1111 in watcher.watched

    async def test_session_without_pid_not_watched(self, running_daemon, sock_path):
        _daemon, _transport, watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1"})
        assert watcher.watched == set()

    async def test_pid_exit_reaps_session(self, running_daemon, sock_path):
        _daemon, transport, watcher = running_daemon
        transport.simulate_connect()
        await asyncio.sleep(0.05)
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send(
            {
                "op": "pretooluse",
                "session_id": "sA",
                "prompt_id": "pA",
                "tool": "Bash",
                "hint": "ls",
                "pid": 9999,
            }
        )
        await asyncio.sleep(0.05)
        hb = json.loads(transport.sent[-1])
        assert hb.get("prompt") is not None

        watcher.fire_exit(9999)
        await asyncio.sleep(0.05)
        hb = json.loads(transport.sent[-1])
        assert hb.get("prompt") is None
        assert hb["total"] == 0

    async def test_session_end_unwatches_pid(self, running_daemon, sock_path):
        _daemon, _transport, watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1", "pid": 4242})
        assert 4242 in watcher.watched
        await client.send({"op": "session_end", "session_id": "s1", "pid": 4242})
        assert 4242 not in watcher.watched

    async def test_exit_event_for_unknown_pid_is_noop(self, running_daemon, sock_path):
        _daemon, _transport, watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "s1", "pid": 111})
        watcher.fire_exit(999)  # not tracked
        resp = await client.send({"op": "status"})
        assert resp["total"] == 1

    async def test_multiple_sessions_share_pid_all_reaped(self, running_daemon, sock_path):
        """If two sessions somehow share a PID, both get reaped on exit."""
        _daemon, _transport, watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "session_start", "session_id": "a", "pid": 5555})
        await client.send({"op": "session_start", "session_id": "b", "pid": 5555})
        watcher.fire_exit(5555)
        await asyncio.sleep(0.02)
        resp = await client.send({"op": "status"})
        assert resp["total"] == 0


class TestTmuxDispatch:
    """Phase 2.1: prefer tmux send-keys over the wrapper when available."""

    async def _make_daemon(self, sock_path: Path, tmux_calls: list, succeeds: bool):
        async def runner(pane: str, keys: list[str]) -> bool:
            tmux_calls.append((pane, keys))
            return succeeds

        transport = FakeTransport()
        watcher = FakeProcessWatcher()
        daemon = Daemon(
            socket_path=sock_path,
            transport=transport,
            heartbeat_period_s=60.0,
            process_watcher=watcher,
            tmux_runner=runner,
        )
        return daemon, transport

    async def test_tmux_pane_routes_to_send_keys_not_wrapper(self, sock_path):
        tmux_calls: list = []
        daemon, transport = await self._make_daemon(sock_path, tmux_calls, succeeds=True)
        task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.02)
        try:
            client = IpcClient(sock_path, total_budget_s=1.0)
            # Wrapper is registered AND tmux pane is present — tmux wins.
            await client.send({"op": "register_wrapper", "child_pid": 1234})
            await client.send(
                {
                    "op": "pretooluse",
                    "session_id": "s-tmux",
                    "prompt_id": "px",
                    "tool": "Bash",
                    "hint": "ls",
                    "pid": 1234,
                    "tmux_pane": "%5",
                }
            )
            poll = asyncio.create_task(
                IpcClient(sock_path, total_budget_s=2.0).send(
                    {"op": "poll_wrapper", "child_pid": 1234, "timeout": 0.3}
                )
            )
            await asyncio.sleep(0.02)
            transport.simulate_receive(
                b'{"cmd":"permission","id":"px","decision":"once"}\n'
            )
            await asyncio.sleep(0.05)
            assert tmux_calls == [("%5", ["y", "Enter"])]
            resp = await asyncio.wait_for(poll, timeout=2.0)
            # Wrapper queue stayed empty because tmux handled it.
            assert resp["decisions"] == []
        finally:
            daemon.shutdown()
            with contextlib.suppress(asyncio.CancelledError, Exception, TimeoutError):
                await asyncio.wait_for(task, timeout=1.0)

    async def test_tmux_failure_falls_back_to_wrapper(self, sock_path):
        tmux_calls: list = []
        daemon, transport = await self._make_daemon(
            sock_path, tmux_calls, succeeds=False
        )
        task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.02)
        try:
            client = IpcClient(sock_path, total_budget_s=1.0)
            await client.send({"op": "register_wrapper", "child_pid": 4321})
            await client.send(
                {
                    "op": "pretooluse",
                    "session_id": "s-fallback",
                    "prompt_id": "py",
                    "tool": "Bash",
                    "hint": "ls",
                    "pid": 4321,
                    "tmux_pane": "%nope",
                }
            )
            poll = asyncio.create_task(
                IpcClient(sock_path, total_budget_s=2.0).send(
                    {"op": "poll_wrapper", "child_pid": 4321, "timeout": 1.0}
                )
            )
            await asyncio.sleep(0.02)
            transport.simulate_receive(
                b'{"cmd":"permission","id":"py","decision":"once"}\n'
            )
            resp = await asyncio.wait_for(poll, timeout=2.0)
            assert tmux_calls == [("%nope", ["y", "Enter"])]
            # Wrapper got the decision because tmux failed.
            assert len(resp["decisions"]) == 1
            assert resp["decisions"][0]["decision"] == "once"
        finally:
            daemon.shutdown()
            with contextlib.suppress(asyncio.CancelledError, Exception, TimeoutError):
                await asyncio.wait_for(task, timeout=1.0)

    async def test_no_tmux_no_wrapper_is_silent_noop(self, sock_path):
        """The session has neither a tmux pane nor a registered wrapper —
        the daemon must not crash; Claude Code's terminal prompt stays in charge."""
        tmux_calls: list = []
        daemon, transport = await self._make_daemon(
            sock_path, tmux_calls, succeeds=False
        )
        task = asyncio.create_task(daemon.run())
        await asyncio.sleep(0.02)
        try:
            client = IpcClient(sock_path, total_budget_s=1.0)
            await client.send(
                {
                    "op": "pretooluse",
                    "session_id": "s-orphan",
                    "prompt_id": "po",
                    "tool": "Bash",
                    "hint": "ls",
                    "pid": 9000,
                }
            )
            transport.simulate_receive(
                b'{"cmd":"permission","id":"po","decision":"once"}\n'
            )
            await asyncio.sleep(0.05)
            assert tmux_calls == []  # no pane → no tmux call attempted
            resp = await client.send({"op": "status"})
            assert resp["ok"] is True
        finally:
            daemon.shutdown()
            with contextlib.suppress(asyncio.CancelledError, Exception, TimeoutError):
                await asyncio.wait_for(task, timeout=1.0)


class TestWrapperRouting:
    """Phase 2: buddy decisions are routed to the wrapper that owns the session."""

    async def test_register_wrapper_without_pid_fails(self, running_daemon, sock_path):
        client = IpcClient(sock_path, total_budget_s=1.0)
        resp = await client.send({"op": "register_wrapper"})
        assert resp["ok"] is False

    async def test_register_then_poll_returns_decision_from_buddy(
        self, running_daemon, sock_path
    ):
        _daemon, transport, _watcher = running_daemon
        # Session's claude-child pid is 1234 (that's what the hook reports).
        CHILD_PID = 1234
        client = IpcClient(sock_path, total_budget_s=1.0)

        await client.send({"op": "register_wrapper", "child_pid": CHILD_PID})
        await client.send(
            {
                "op": "pretooluse",
                "session_id": "s1",
                "prompt_id": "p1",
                "tool": "Bash",
                "hint": "ls",
                "pid": CHILD_PID,
            }
        )
        # Start a long-poll.
        poll_client = IpcClient(sock_path, total_budget_s=5.0)
        poll_task = asyncio.create_task(
            poll_client.send(
                {"op": "poll_wrapper", "child_pid": CHILD_PID, "timeout": 3.0}
            )
        )
        await asyncio.sleep(0.02)
        # Buddy approves.
        transport.simulate_receive(
            b'{"cmd":"permission","id":"p1","decision":"once"}\n'
        )
        resp = await asyncio.wait_for(poll_task, timeout=3.0)
        assert resp["ok"] is True
        assert len(resp["decisions"]) == 1
        assert resp["decisions"][0]["decision"] == "once"
        assert resp["decisions"][0]["prompt_id"] == "p1"
        assert resp["decisions"][0]["session_id"] == "s1"

    async def test_poll_without_register_returns_error(self, running_daemon, sock_path):
        client = IpcClient(sock_path, total_budget_s=1.0)
        resp = await client.send({"op": "poll_wrapper", "child_pid": 999})
        assert resp["ok"] is False

    async def test_poll_timeout_returns_empty_decisions(self, running_daemon, sock_path):
        client = IpcClient(sock_path, total_budget_s=2.0)
        await client.send({"op": "register_wrapper", "child_pid": 42})
        resp = await client.send(
            {"op": "poll_wrapper", "child_pid": 42, "timeout": 0.1}
        )
        assert resp["ok"] is True
        assert resp["decisions"] == []

    async def test_decision_without_registered_wrapper_is_dropped(
        self, running_daemon, sock_path
    ):
        """No wrapper registered — decisions are still processed but not queued."""
        _daemon, transport, _watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send(
            {
                "op": "pretooluse",
                "session_id": "lone",
                "prompt_id": "p1",
                "tool": "Bash",
                "hint": "ls",
                "pid": 7777,
            }
        )
        transport.simulate_receive(
            b'{"cmd":"permission","id":"p1","decision":"once"}\n'
        )
        # No exceptions, daemon survives, status is sane.
        resp = await client.send({"op": "status"})
        assert resp["ok"] is True

    async def test_unregister_wrapper_is_idempotent(self, running_daemon, sock_path):
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "register_wrapper", "child_pid": 8888})
        r1 = await client.send({"op": "unregister_wrapper", "child_pid": 8888})
        r2 = await client.send({"op": "unregister_wrapper", "child_pid": 8888})
        assert r1["ok"] is True
        assert r2["ok"] is True
        # poll after unregister → not registered
        resp = await client.send({"op": "poll_wrapper", "child_pid": 8888})
        assert resp["ok"] is False

    async def test_deny_decision_not_pushed_to_wrapper_or_tmux(
        self, running_daemon, sock_path
    ):
        """We never auto-inject 'n' — the user can type it themselves."""
        _daemon, transport, _watcher = running_daemon
        client = IpcClient(sock_path, total_budget_s=1.0)
        await client.send({"op": "register_wrapper", "child_pid": 5000})
        await client.send(
            {
                "op": "pretooluse",
                "session_id": "s5",
                "prompt_id": "pd",
                "tool": "Bash",
                "hint": "rm -rf /",
                "pid": 5000,
            }
        )
        poll = asyncio.create_task(
            IpcClient(sock_path, total_budget_s=2.0).send(
                {"op": "poll_wrapper", "child_pid": 5000, "timeout": 0.3}
            )
        )
        await asyncio.sleep(0.02)
        transport.simulate_receive(
            b'{"cmd":"permission","id":"pd","decision":"deny"}\n'
        )
        resp = await asyncio.wait_for(poll, timeout=2.0)
        assert resp["decisions"] == []
