from __future__ import annotations

import asyncio
import os
import sys

import pytest

from claude_buddy_bridge.process_watcher import (
    KqueueProcessWatcher,
    PollingProcessWatcher,
    _default_alive,
    make_process_watcher,
)


class TestDefaultAlive:
    def test_self_pid_is_alive(self):
        assert _default_alive(os.getpid()) is True

    def test_dead_pid_is_not_alive(self):
        assert _default_alive(2**31 - 1) is False


class TestPollingWatcher:
    async def test_exit_callback_fires_when_alive_returns_false(self):
        alive_map = {1111: True, 2222: True}
        watcher = PollingProcessWatcher(
            period_s=0.02, alive=lambda pid: alive_map.get(pid, False)
        )
        exited: list[int] = []
        watcher.set_exit_callback(exited.append)
        watcher.watch(1111)
        watcher.watch(2222)
        await watcher.start()
        try:
            await asyncio.sleep(0.1)
            assert exited == []
            alive_map[1111] = False
            await asyncio.sleep(0.08)
            assert exited == [1111]
        finally:
            await watcher.stop()

    async def test_unwatch_prevents_callback(self):
        watcher = PollingProcessWatcher(period_s=0.02, alive=lambda _: False)
        exited: list[int] = []
        watcher.set_exit_callback(exited.append)
        watcher.watch(9999)
        watcher.unwatch(9999)
        await watcher.start()
        try:
            await asyncio.sleep(0.08)
            assert exited == []
        finally:
            await watcher.stop()


@pytest.mark.skipif(
    not (sys.platform == "darwin" or sys.platform.startswith("freebsd")),
    reason="kqueue is BSD-only",
)
class TestKqueueWatcher:
    async def test_child_exit_fires_callback(self):
        watcher = KqueueProcessWatcher()
        await watcher.start()
        exited: list[int] = []
        watcher.set_exit_callback(exited.append)
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", "sleep 0.05"
            )
            watcher.watch(proc.pid)
            await proc.wait()
            # kqueue fires on loop iteration; give it a tick
            for _ in range(50):
                if exited:
                    break
                await asyncio.sleep(0.01)
            assert exited == [proc.pid]
        finally:
            await watcher.stop()

    async def test_watch_dead_pid_fires_callback(self):
        watcher = KqueueProcessWatcher()
        await watcher.start()
        exited: list[int] = []
        watcher.set_exit_callback(exited.append)
        try:
            proc = await asyncio.create_subprocess_exec("/bin/sh", "-c", "exit 0")
            await proc.wait()
            watcher.watch(proc.pid)  # process is already gone
            for _ in range(50):
                if exited:
                    break
                await asyncio.sleep(0.01)
            assert exited == [proc.pid]
        finally:
            await watcher.stop()

    async def test_unwatch_before_exit(self):
        watcher = KqueueProcessWatcher()
        await watcher.start()
        exited: list[int] = []
        watcher.set_exit_callback(exited.append)
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", "sleep 0.2"
            )
            watcher.watch(proc.pid)
            watcher.unwatch(proc.pid)
            await proc.wait()
            await asyncio.sleep(0.1)
            assert exited == []
        finally:
            await watcher.stop()

    async def test_watch_before_start_on_dead_pid_does_not_crash(self):
        """Calling watch() with no running loop and no start() must not raise."""
        watcher = KqueueProcessWatcher()
        # Do NOT call start(); just attempt to watch an obviously-dead PID.
        watcher.watch(2**31 - 1)
        # Start afterwards; the watcher should still be usable.
        await watcher.start()
        await watcher.stop()

    async def test_double_watch_is_idempotent(self):
        watcher = KqueueProcessWatcher()
        await watcher.start()
        try:
            proc = await asyncio.create_subprocess_exec(
                "/bin/sh", "-c", "sleep 0.05"
            )
            watcher.watch(proc.pid)
            watcher.watch(proc.pid)
            exited: list[int] = []
            watcher.set_exit_callback(exited.append)
            await proc.wait()
            for _ in range(50):
                if exited:
                    break
                await asyncio.sleep(0.01)
            assert exited == [proc.pid]
        finally:
            await watcher.stop()


class TestFactory:
    def test_make_returns_kqueue_on_darwin(self):
        if sys.platform == "darwin":
            assert isinstance(make_process_watcher(), KqueueProcessWatcher)

    def test_make_returns_polling_on_linux(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert isinstance(make_process_watcher(), PollingProcessWatcher)
