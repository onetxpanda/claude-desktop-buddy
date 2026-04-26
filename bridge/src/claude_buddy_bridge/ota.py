"""BLE OTA driver.

Pushes a firmware image to a connected buddy device using the protocol
defined in docs/superpowers/specs/2026-04-26-phase-c-ble-ota-design.md
on the firmware side. The state machine on the device end lives in
src/ota.{h,cpp} of the firmware repo.

Wire format (this side sends `cmd:`, device replies with `evt:`):

    cmd:ota_begin  {size, sha256, version}    →   evt:ota_ready  | evt:ota_error
    cmd:ota_data   {seq, b64}                  →   evt:ota_ack    (every 32nd)
                                                  evt:ota_progress (every 64th)
    cmd:ota_commit                             →   evt:ota_committed (then disconnect)
                                                  evt:ota_error
    cmd:ota_abort                              →   evt:ota_aborted

Throughput at the typical macOS MTU of 185 is ~120 bytes of binary
payload per chunk, ~6 ms wall per chunk → ~55 s for a 1.1 MB image.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from .ble import Transport
from .protocol import (
    OtaAborted,
    OtaAck,
    OtaCommitted,
    OtaError,
    OtaProgress,
    OtaReady,
    decode_device_line,
)

log = logging.getLogger(__name__)


# Bytes of binary payload per ota_data chunk. At MTU 185 the BLE notify
# can carry ~182 bytes after ATT overhead. base64 encodes 3 bytes → 4
# chars + JSON envelope overhead (~40 bytes) leaves us a safe ~120 binary
# bytes per chunk, rounded down to 117 (= 39 × 3) so the base64 encoded
# payload aligns with the natural 4-char block size with no padding.
DEFAULT_CHUNK_BYTES = 117


class OtaFailed(RuntimeError):
    """OTA push failed before reaching evt:ota_committed."""


ProgressCb = Callable[[int, int], None]  # (received_bytes, total_bytes)


@dataclass
class _Inbox:
    """Rendezvous for device-emitted evt:ota_* messages.

    The transport's line listener already receives newline-split lines
    (LineReader runs in the transport itself), so we just decode each
    line directly — no buffering here.
    """

    queue: asyncio.Queue

    def feed(self, line: bytes) -> None:
        try:
            msg = decode_device_line(line)
        except Exception as e:  # noqa: BLE001 - protocol robustness
            log.debug("ota: parse error %s on %r", e, line)
            return
        if msg is None:
            return  # parser tolerated an unknown shape
        self.queue.put_nowait(msg)


async def _await_event(inbox: _Inbox, expected: type, timeout: float) -> object:
    """Wait for an evt of the expected type. Raises OtaFailed on
    OtaError, asyncio.TimeoutError on timeout."""

    while True:
        msg = await asyncio.wait_for(inbox.queue.get(), timeout=timeout)
        if isinstance(msg, OtaError):
            raise OtaFailed(f"device error: {msg.msg}")
        if isinstance(msg, expected):
            return msg
        # Other evt:ota_* (progress, ack) — pass through to next poll.
        log.debug("ota: dropping intermediate %r", msg)


def _begin_line(image: bytes, version: str) -> bytes:
    sha = hashlib.sha256(image).hexdigest()
    payload = {
        "cmd": "ota_begin",
        "size": len(image),
        "sha256": sha,
        "version": version,
    }
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


def _data_line(seq: int, chunk: bytes) -> bytes:
    payload = {
        "cmd": "ota_data",
        "seq": seq,
        "b64": base64.b64encode(chunk).decode("ascii"),
    }
    return (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")


_COMMIT_LINE = b'{"cmd":"ota_commit"}\n'
_ABORT_LINE = b'{"cmd":"ota_abort"}\n'


async def push_firmware(
    transport: Transport,
    image: bytes,
    version: str,
    progress: ProgressCb | None = None,
    chunk_bytes: int = DEFAULT_CHUNK_BYTES,
    begin_timeout: float = 5.0,
    ack_timeout: float = 2.0,
    commit_timeout: float = 10.0,
) -> None:
    """Push `image` to the device. Raises OtaFailed on protocol error
    or timeout, asyncio.TimeoutError if the device stops responding.

    The transport must already be connected. The caller's existing
    line listener is replaced for the duration of the push and restored
    on exit (success or failure)."""

    if not transport.connected:
        raise OtaFailed("transport not connected")

    inbox = _Inbox(queue=asyncio.Queue())

    # Hijack the line listener for the duration of the push. Save and
    # restore the original so the daemon's regular heartbeat dispatch
    # picks back up cleanly (or, if the device rebooted post-commit,
    # picks up after reconnect).
    transport.set_line_listener(inbox.feed)

    total = len(image)
    received = 0

    try:
        await transport.send_line(_begin_line(image, version))
        await _await_event(inbox, OtaReady, begin_timeout)

        seq = 0
        last_acked_seq: int | None = None
        for offset in range(0, total, chunk_bytes):
            chunk = image[offset : offset + chunk_bytes]
            await transport.send_line(_data_line(seq, chunk))
            received += len(chunk)
            seq += 1
            if progress is not None:
                progress(received, total)

            # Device acks every 32 chunks. Wait for it before continuing
            # so we bound how far ahead we can get.
            if seq % 32 == 0:
                ack = await _await_event(inbox, OtaAck, ack_timeout)
                assert isinstance(ack, OtaAck)
                if ack.seq != seq - 1:
                    raise OtaFailed(
                        f"ack seq mismatch: device acked {ack.seq}, expected {seq - 1}"
                    )
                last_acked_seq = ack.seq

        await transport.send_line(_COMMIT_LINE)
        # On success, device emits evt:ota_committed and disconnects.
        # Either is a valid completion signal.
        try:
            await _await_event(inbox, OtaCommitted, commit_timeout)
        except asyncio.TimeoutError:
            if not transport.connected:
                # Device rebooted before we got the committed evt — also success.
                pass
            else:
                raise

    except Exception:
        # Best-effort abort so the device doesn't sit in Receiving forever.
        try:
            await transport.send_line(_ABORT_LINE)
            await _await_event(inbox, OtaAborted, 1.0)
        except Exception:  # noqa: BLE001 - cleanup is best-effort
            pass
        raise
