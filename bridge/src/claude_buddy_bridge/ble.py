"""BLE transport for the buddy device.

The :class:`Transport` abstract base pins the minimal surface the daemon needs
so we can swap in :class:`FakeTransport` for unit tests. :class:`BleakTransport`
is the production implementation and is exercised manually against real
hardware rather than in unit tests.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable

from .protocol import LineReader

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX_CHAR = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
DEVICE_NAME_PREFIX = "Claude"

log = logging.getLogger(__name__)

LineListener = Callable[[bytes], None]
ConnListener = Callable[[bool], None]


class Transport(ABC):
    """Minimal buddy-device transport surface."""

    connected: bool = False

    @abstractmethod
    def set_line_listener(self, cb: LineListener) -> None: ...

    @abstractmethod
    def set_connection_listener(self, cb: ConnListener) -> None: ...

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send_line(self, line: bytes) -> None: ...


class FakeTransport(Transport):
    """In-memory transport for daemon integration tests."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self._line_cb: LineListener | None = None
        self._conn_cb: ConnListener | None = None
        self._reader = LineReader()

    def set_line_listener(self, cb: LineListener) -> None:
        self._line_cb = cb

    def set_connection_listener(self, cb: ConnListener) -> None:
        self._conn_cb = cb

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        if self.connected:
            self._set_connected(False)

    async def send_line(self, line: bytes) -> None:
        self.sent.append(line)

    # --- test helpers ------------------------------------------------------

    def simulate_connect(self) -> None:
        self._set_connected(True)

    def simulate_disconnect(self) -> None:
        self._set_connected(False)

    def simulate_receive(self, raw: bytes) -> None:
        if self._line_cb is None:
            return
        for line in self._reader.feed(raw):
            self._line_cb(line)

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        if self._conn_cb is not None:
            self._conn_cb(connected)


class BleakTransport(Transport):
    """Production BLE transport. Only exercised against real hardware."""

    def __init__(
        self,
        *,
        reconnect_delay_s: float = 2.0,
        scan_timeout_s: float = 10.0,
    ) -> None:
        self._reconnect_delay = reconnect_delay_s
        self._scan_timeout = scan_timeout_s
        self._line_cb: LineListener | None = None
        self._conn_cb: ConnListener | None = None
        self._client = None
        self._run_task: asyncio.Task | None = None
        self._stop_evt = asyncio.Event()
        self._reader = LineReader()

    def set_line_listener(self, cb: LineListener) -> None:
        self._line_cb = cb

    def set_connection_listener(self, cb: ConnListener) -> None:
        self._conn_cb = cb

    async def start(self) -> None:
        self._stop_evt.clear()
        self._run_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stop_evt.set()
        task = self._run_task
        self._run_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        await self._disconnect()

    async def send_line(self, line: bytes) -> None:
        if not self.connected or self._client is None:
            return
        try:
            await self._client.write_gatt_char(NUS_RX_CHAR, line, response=False)
        except Exception as e:  # pragma: no cover - hardware path
            log.warning("BLE send failed: %s", e)

    async def _run_loop(self) -> None:  # pragma: no cover - hardware path
        from bleak import BleakClient, BleakScanner

        while not self._stop_evt.is_set():
            try:
                device = await BleakScanner.find_device_by_filter(
                    lambda d, _adv: bool(
                        d.name and d.name.startswith(DEVICE_NAME_PREFIX)
                    ),
                    timeout=self._scan_timeout,
                )
                if device is None:
                    await asyncio.sleep(self._reconnect_delay)
                    continue

                client = BleakClient(device)
                # Assign before connect so an in-flight stop() can still
                # disconnect the partially-established client.
                self._client = client
                await client.connect()
                await client.start_notify(NUS_TX_CHAR, self._on_notify)
                self._set_connected(True)

                while client.is_connected and not self._stop_evt.is_set():
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("BLE loop error: %s", e)
            finally:
                await self._disconnect()
            if not self._stop_evt.is_set():
                await asyncio.sleep(self._reconnect_delay)

    def _on_notify(self, _char, data: bytearray) -> None:  # pragma: no cover
        if self._line_cb is None:
            return
        for line in self._reader.feed(bytes(data)):
            try:
                self._line_cb(line)
            except Exception:
                log.exception("line listener raised")

    async def _disconnect(self) -> None:
        client = self._client
        self._client = None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.disconnect()
        self._set_connected(False)

    def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        if self._conn_cb is not None:
            try:
                self._conn_cb(connected)
            except Exception:
                log.exception("connection listener raised")
