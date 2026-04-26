"""High-level OTA update driver — the brain behind ``claude-buddy update``.

Connects to a paired buddy device, waits for its evt:info banner so we
know which board it is and whether it advertises ota_v1, then pushes a
firmware image via :func:`claude_buddy_bridge.ota.push_firmware` with a
plain stderr progress line. Stays out of the daemon's path entirely so
the update flow doesn't require ``claude-buddy start`` to be running.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from .ble import BleakTransport, Transport
from .ota import OtaFailed, push_firmware
from .protocol import Info, decode_device_line

log = logging.getLogger(__name__)


class _InfoWaiter:
    """Captures the next evt:info while letting the rest fall through."""

    def __init__(self) -> None:
        self.info: Info | None = None
        self._evt = asyncio.Event()
        self._chained: list[bytes] = []

    def feed(self, line: bytes) -> None:
        if self.info is None:
            try:
                msg = decode_device_line(line)
            except Exception:  # noqa: BLE001 - best-effort while waiting
                msg = None
            if isinstance(msg, Info):
                self.info = msg
                self._evt.set()
                return
        # Anything other than the info we're waiting for is ignored
        # — the update CLI doesn't need the heartbeat stream.

    async def wait(self, timeout: float) -> Info | None:
        try:
            await asyncio.wait_for(self._evt.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return self.info


async def _wait_connected(transport: Transport, timeout: float) -> bool:
    """Block until transport.connected or deadline. Polls — the
    connection-listener API only fires on edge transitions, and we
    might already be connected by the time we register."""

    deadline = asyncio.get_event_loop().time() + timeout
    while not transport.connected:
        if asyncio.get_event_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.1)
    return True


def _stderr_progress(received: int, total: int) -> None:
    pct = (received * 100) // total if total else 0
    bar_len = 30
    filled = (received * bar_len) // total if total else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stderr.write(
        f"\r  [{bar}] {pct:3d}%  {received:>8} / {total:<8} bytes"
    )
    sys.stderr.flush()
    if received >= total:
        sys.stderr.write("\n")


async def run_update(
    file_path: Path,
    version: str | None = None,
    require_feature: bool = True,
    connect_timeout_s: float = 30.0,
    info_timeout_s: float = 5.0,
) -> int:
    """Implement ``claude-buddy update --file ...``. Returns a process
    exit code (0 success, non-zero on failure)."""

    if not file_path.exists():
        print(f"error: {file_path} does not exist", file=sys.stderr)
        return 2
    image = file_path.read_bytes()
    if not image:
        print(f"error: {file_path} is empty", file=sys.stderr)
        return 2

    if version is None:
        # Default to the filename so the device's evt:info echoes
        # something recognizable in the next heartbeat.
        version = file_path.stem

    print(f"  image:   {file_path} ({len(image):,} bytes)", file=sys.stderr)
    print(f"  version: {version}", file=sys.stderr)
    print("  scanning for buddy device...", file=sys.stderr)

    transport = BleakTransport()
    info_waiter = _InfoWaiter()
    transport.set_line_listener(info_waiter.feed)

    await transport.start()
    try:
        if not await _wait_connected(transport, connect_timeout_s):
            print(
                f"error: no buddy device connected within {connect_timeout_s}s. "
                "Is it powered on and paired?",
                file=sys.stderr,
            )
            return 3

        print("  connected. waiting for evt:info...", file=sys.stderr)
        info = await info_waiter.wait(info_timeout_s)
        if info is None and require_feature:
            print(
                f"error: device didn't send evt:info within {info_timeout_s}s. "
                "Either it's running an older firmware that predates Phase C "
                "(no info banner), or the link is flaky. Pass "
                "--no-feature-check to push anyway.",
                file=sys.stderr,
            )
            return 4
        if info is not None:
            print(
                f"  device:  {info.board} @ {info.version}  "
                f"features={list(info.features)}",
                file=sys.stderr,
            )
            if require_feature and "ota_v1" not in info.features:
                print(
                    "error: device firmware does not advertise ota_v1 — it can't "
                    "process cmd:ota_*. Flash a newer build via USB first, or "
                    "pass --no-feature-check to push anyway.",
                    file=sys.stderr,
                )
                return 5

        print("  pushing firmware...", file=sys.stderr)
        try:
            await push_firmware(
                transport, image, version=version, progress=_stderr_progress
            )
        except OtaFailed as e:
            print(f"\nerror: OTA failed: {e}", file=sys.stderr)
            return 6
        print(
            "  done. device will reboot into the new firmware shortly.",
            file=sys.stderr,
        )
        return 0
    finally:
        await transport.stop()
