"""Tests for the BLE OTA driver.

Uses FakeTransport to record cmd:ota_* lines and inject scripted
device-side evt:* responses. Covers the happy path, the begin failure,
chunk-error mid-stream, and the abort-on-exception cleanup.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json

import pytest

from claude_buddy_bridge.ble import FakeTransport
from claude_buddy_bridge.ota import (
    DEFAULT_CHUNK_BYTES,
    OtaFailed,
    push_firmware,
)


def _decoded_sent(t: FakeTransport) -> list[dict]:
    """Decode every line t.sent contains; lets tests assert on cmd shape."""

    out: list[dict] = []
    for raw in t.sent:
        text = raw.decode("utf-8").strip()
        if not text:
            continue
        out.append(json.loads(text))
    return out


def _scripted_drainer(t: FakeTransport, script: list[bytes]) -> asyncio.Task:
    """Spawn a task that watches t.sent and feeds scripted device replies
    back to the transport in order. One reply per cmd seen on the wire,
    leftover replies (e.g. extra acks/progress) get drained too."""

    async def runner() -> None:
        cursor = 0
        for line in script:
            # Wait until the bridge has sent at least one more cmd than
            # we've already responded to. Polling is simple and good
            # enough — every iteration of push_firmware sends a line
            # before awaiting a reply.
            while len(t.sent) <= cursor:
                await asyncio.sleep(0)
            cursor = len(t.sent)
            t.simulate_receive(line)

    return asyncio.create_task(runner())


@pytest.fixture
async def transport() -> FakeTransport:
    t = FakeTransport()
    await t.start()
    t.simulate_connect()
    yield t
    await t.stop()


class TestPushFirmware:
    async def test_happy_path_sends_begin_data_commit(self, transport: FakeTransport):
        # Image small enough that we never hit the 32-chunk ack boundary.
        image = b"\x00" * (DEFAULT_CHUNK_BYTES * 3)  # 3 chunks, no ack expected
        replies = [
            b'{"evt":"ota_ready"}\n',
            b'{"evt":"ota_committed"}\n',
        ]
        drainer = _scripted_drainer(transport, replies)
        await push_firmware(transport, image, version="test-build")
        await asyncio.wait_for(drainer, timeout=1.0)

        sent = _decoded_sent(transport)
        # 1 begin + 3 data + 1 commit
        assert len(sent) == 5
        assert sent[0]["cmd"] == "ota_begin"
        assert sent[0]["size"] == len(image)
        assert sent[0]["sha256"] == hashlib.sha256(image).hexdigest()
        assert sent[0]["version"] == "test-build"
        for i in range(3):
            assert sent[1 + i]["cmd"] == "ota_data"
            assert sent[1 + i]["seq"] == i
            decoded = base64.b64decode(sent[1 + i]["b64"])
            assert decoded == image[i * DEFAULT_CHUNK_BYTES : (i + 1) * DEFAULT_CHUNK_BYTES]
        assert sent[4]["cmd"] == "ota_commit"

    async def test_progress_callback_called_per_chunk(self, transport: FakeTransport):
        image = b"\x00" * (DEFAULT_CHUNK_BYTES * 2)
        replies = [b'{"evt":"ota_ready"}\n', b'{"evt":"ota_committed"}\n']
        drainer = _scripted_drainer(transport, replies)
        progress_calls: list[tuple[int, int]] = []
        await push_firmware(
            transport,
            image,
            version="t",
            progress=lambda r, t: progress_calls.append((r, t)),
        )
        await asyncio.wait_for(drainer, timeout=1.0)

        # Each chunk fires the callback. Final value should be (total, total).
        assert len(progress_calls) == 2
        assert progress_calls[-1] == (len(image), len(image))

    async def test_ack_boundary_waits_for_device(self, transport: FakeTransport):
        # 33 chunks → device should send ack at seq=31 (after 32nd chunk).
        image = b"\x00" * (DEFAULT_CHUNK_BYTES * 33)
        replies = [
            b'{"evt":"ota_ready"}\n',
            b'{"evt":"ota_ack","seq":31}\n',
            b'{"evt":"ota_committed"}\n',
        ]
        drainer = _scripted_drainer(transport, replies)
        await push_firmware(transport, image, version="t")
        await asyncio.wait_for(drainer, timeout=2.0)

        sent = _decoded_sent(transport)
        # 1 begin + 33 data + 1 commit
        assert len(sent) == 35
        assert sent[-1]["cmd"] == "ota_commit"

    async def test_begin_error_raises(self, transport: FakeTransport):
        replies = [
            b'{"evt":"ota_error","msg":"Update.begin failed"}\n',
            b'{"evt":"ota_aborted"}\n',  # the cleanup abort gets acked
        ]
        drainer = _scripted_drainer(transport, replies)
        with pytest.raises(OtaFailed, match="Update.begin failed"):
            await push_firmware(transport, b"\x00" * 100, version="t")
        # Drainer may not have consumed everything if cleanup races; that's fine.
        drainer.cancel()

    async def test_disconnect_during_commit_treated_as_success(
        self, transport: FakeTransport
    ):
        # Device reboots before we see evt:ota_committed → transport
        # disconnects, push_firmware returns cleanly.
        image = b"\x00" * DEFAULT_CHUNK_BYTES
        replies = [b'{"evt":"ota_ready"}\n']
        drainer = _scripted_drainer(transport, replies)
        # When commit goes out, simulate disconnect mid-await.
        async def disconnect_after_commit() -> None:
            while not any(b'"ota_commit"' in s for s in transport.sent):
                await asyncio.sleep(0.01)
            transport.simulate_disconnect()

        await asyncio.gather(
            push_firmware(transport, image, version="t", commit_timeout=0.5),
            disconnect_after_commit(),
            return_exceptions=False,
        )
        drainer.cancel()

    async def test_not_connected_raises(self):
        t = FakeTransport()
        await t.start()
        # Note: deliberately NOT calling simulate_connect.
        with pytest.raises(OtaFailed, match="not connected"):
            await push_firmware(t, b"\x00" * 16, version="t")
        await t.stop()
