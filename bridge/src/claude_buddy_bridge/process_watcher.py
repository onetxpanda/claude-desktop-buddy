"""Process-exit notifications.

The production path on macOS uses ``kqueue`` with ``EVFILT_PROC`` /
``NOTE_EXIT``: the kernel pins the registration to the specific process (not
to the numeric PID), so exits are detected with sub-millisecond latency and
PID reuse cannot race us. On other platforms we fall back to polling.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Callable

log = logging.getLogger(__name__)

ExitCallback = Callable[[int], None]


class ProcessWatcher(ABC):
    """Notifies when a registered process exits. Implementations dedupe PIDs."""

    @abstractmethod
    def set_exit_callback(self, cb: ExitCallback) -> None: ...

    @abstractmethod
    def watch(self, pid: int) -> None:
        """Register interest in `pid`. Idempotent."""

    @abstractmethod
    def unwatch(self, pid: int) -> None:
        """Stop watching `pid`. Safe to call for unwatched pids."""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...


class KqueueProcessWatcher(ProcessWatcher):
    """kqueue-backed watcher for Darwin / BSD."""

    def __init__(self) -> None:
        import select

        self._select = select
        self._kq = select.kqueue()
        self._watched: set[int] = set()
        self._cb: ExitCallback | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_exit_callback(self, cb: ExitCallback) -> None:
        self._cb = cb

    def watch(self, pid: int) -> None:
        if pid in self._watched:
            return
        ev = self._select.kevent(
            pid,
            filter=self._select.KQ_FILTER_PROC,
            flags=(
                self._select.KQ_EV_ADD
                | self._select.KQ_EV_ENABLE
                | self._select.KQ_EV_ONESHOT
            ),
            fflags=self._select.KQ_NOTE_EXIT,
        )
        try:
            self._kq.control([ev], 0)
        except ProcessLookupError:
            # Already dead — fire on the next loop iteration so the caller's
            # current state mutation completes first.
            loop = self._loop
            if loop is None:
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    # No running loop and start() has not been awaited — caller
                    # is misusing the API. Drop silently; the session will not
                    # be tracked at all rather than be falsely marked alive.
                    log.warning("watch(%d): no running loop, dropping", pid)
                    return
            loop.call_soon(self._fire, pid)
            return
        except OSError as e:
            log.warning("kqueue watch(%d) failed: %s", pid, e)
            return
        self._watched.add(pid)

    def unwatch(self, pid: int) -> None:
        if pid not in self._watched:
            return
        ev = self._select.kevent(
            pid,
            filter=self._select.KQ_FILTER_PROC,
            flags=self._select.KQ_EV_DELETE,
        )
        with contextlib.suppress(OSError):
            self._kq.control([ev], 0)
        self._watched.discard(pid)

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._loop.add_reader(self._kq.fileno(), self._drain)

    async def stop(self) -> None:
        if self._loop is not None:
            with contextlib.suppress(ValueError, OSError):
                self._loop.remove_reader(self._kq.fileno())
        self._watched.clear()
        with contextlib.suppress(OSError):
            self._kq.close()

    def _drain(self) -> None:
        try:
            events = self._kq.control([], 16, 0)
        except OSError as e:
            log.warning("kqueue drain failed: %s", e)
            return
        for e in events:
            if (
                e.filter == self._select.KQ_FILTER_PROC
                and e.fflags & self._select.KQ_NOTE_EXIT
            ):
                self._fire(int(e.ident))

    def _fire(self, pid: int) -> None:
        self._watched.discard(pid)
        if self._cb is not None:
            try:
                self._cb(pid)
            except Exception:
                log.exception("exit callback raised")


class PollingProcessWatcher(ProcessWatcher):
    """Fallback watcher that polls ``os.kill(pid, 0)`` on a timer."""

    def __init__(
        self,
        *,
        period_s: float = 5.0,
        alive: Callable[[int], bool] | None = None,
    ) -> None:
        self._period = period_s
        self._watched: set[int] = set()
        self._cb: ExitCallback | None = None
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._alive = alive or _default_alive

    def set_exit_callback(self, cb: ExitCallback) -> None:
        self._cb = cb

    def watch(self, pid: int) -> None:
        self._watched.add(pid)

    def unwatch(self, pid: int) -> None:
        self._watched.discard(pid)

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._watched.clear()

    async def _run(self) -> None:
        while not self._stop.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=self._period)
            if self._stop.is_set():
                return
            for pid in list(self._watched):
                if not self._alive(pid):
                    self._watched.discard(pid)
                    if self._cb is not None:
                        try:
                            self._cb(pid)
                        except Exception:
                            log.exception("exit callback raised")


def _default_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def make_process_watcher() -> ProcessWatcher:
    """Return the best watcher available on this platform."""
    if sys.platform == "darwin" or sys.platform.startswith("freebsd"):
        try:
            return KqueueProcessWatcher()
        except OSError as e:
            log.warning("falling back to polling watcher: %s", e)
    return PollingProcessWatcher()
