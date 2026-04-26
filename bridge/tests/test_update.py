"""Tests for ``claude-buddy update`` orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from claude_buddy_bridge.ble import FakeTransport
from claude_buddy_bridge.update import _InfoWaiter, run_update


# ---------------------------------------------------------------------------
# _InfoWaiter — the small helper that captures the first evt:info line.
# ---------------------------------------------------------------------------


class TestInfoWaiter:
    async def test_returns_info_on_match(self):
        w = _InfoWaiter()
        w.feed(
            b'{"evt":"info","board":"m5stack-core2","version":"x@abc","features":["ota_v1"]}'
        )
        info = await w.wait(0.5)
        assert info is not None
        assert info.board == "m5stack-core2"
        assert info.version == "x@abc"
        assert info.features == ("ota_v1",)

    async def test_ignores_other_lines(self):
        w = _InfoWaiter()
        w.feed(b'{"evt":"ota_progress","pct":12}')
        w.feed(b'{"random":"shape"}')
        info = await w.wait(0.05)
        assert info is None

    async def test_only_first_info_wins(self):
        # If two evt:info arrive (shouldn't happen, but be defensive),
        # waiter holds the first one.
        w = _InfoWaiter()
        w.feed(
            b'{"evt":"info","board":"m5stack-core2","version":"v1","features":["ota_v1"]}'
        )
        w.feed(
            b'{"evt":"info","board":"m5stack-core2","version":"v2","features":[]}'
        )
        info = await w.wait(0.05)
        assert info is not None
        assert info.version == "v1"

    async def test_timeout_returns_none(self):
        w = _InfoWaiter()
        info = await w.wait(0.05)
        assert info is None


# ---------------------------------------------------------------------------
# run_update — the orchestrator. We swap in a FakeTransport via monkeypatch
# so the test never touches bleak / actual BLE.
# ---------------------------------------------------------------------------


@pytest.fixture
def firmware_file(tmp_path: Path) -> Path:
    p = tmp_path / "firmware.bin"
    p.write_bytes(b"\x00\x01\x02" * 64)  # 192 bytes — fits in two chunks
    return p


def _scripted_drainer(
    transport: FakeTransport,
    lines: list[bytes],
    info_first: bool = True,
) -> asyncio.Task:
    """Feeds device-side replies into the transport.

    The first line (evt:info) is delivered as soon as anyone is
    listening — the device pushes it on connect, before the bridge
    sends anything. Subsequent lines wait for the bridge to send a new
    line first (so they arrive as responses to begin/commit etc).
    """

    async def runner() -> None:
        cursor = 0
        for i, raw in enumerate(lines):
            if i == 0 and info_first:
                # Yield once so the run_update coroutine has a chance to
                # register its line listener first.
                await asyncio.sleep(0.01)
            else:
                while len(transport.sent) <= cursor:
                    await asyncio.sleep(0.005)
                cursor = len(transport.sent)
            transport.simulate_receive(raw)

    return asyncio.create_task(runner())


async def _patched_update(
    monkeypatch: pytest.MonkeyPatch,
    *,
    transport: FakeTransport,
    drainer_lines: list[bytes],
    info_first: bool = True,
    **kwargs,
) -> int:
    """run_update wired to a FakeTransport via monkeypatch."""

    # The transport has to look already-connected so _wait_connected
    # returns immediately; tests that want to exercise the timeout path
    # leave it disconnected.
    if kwargs.pop("simulate_connect", True):
        transport.simulate_connect()

    drain = _scripted_drainer(transport, drainer_lines, info_first=info_first)

    # run_update constructs a BleakTransport — replace the constructor.
    monkeypatch.setattr(
        "claude_buddy_bridge.update.BleakTransport", lambda *_a, **_k: transport
    )

    try:
        rc = await run_update(**kwargs)
    finally:
        drain.cancel()
    return rc


class TestRunUpdate:
    async def test_missing_file_exits_2(self, tmp_path: Path):
        rc = await run_update(file_path=tmp_path / "nope.bin")
        assert rc == 2

    async def test_empty_file_exits_2(self, tmp_path: Path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        rc = await run_update(file_path=f)
        assert rc == 2

    async def test_no_connect_exits_3(
        self, monkeypatch: pytest.MonkeyPatch, firmware_file: Path
    ):
        t = FakeTransport()
        rc = await _patched_update(
            monkeypatch,
            transport=t,
            drainer_lines=[],
            file_path=firmware_file,
            connect_timeout_s=0.1,
            simulate_connect=False,
        )
        assert rc == 3

    async def test_no_info_with_check_exits_4(
        self, monkeypatch: pytest.MonkeyPatch, firmware_file: Path
    ):
        t = FakeTransport()
        rc = await _patched_update(
            monkeypatch,
            transport=t,
            drainer_lines=[],  # no evt:info — waiter times out
            file_path=firmware_file,
            info_timeout_s=0.1,
        )
        assert rc == 4

    async def test_missing_ota_feature_exits_5(
        self, monkeypatch: pytest.MonkeyPatch, firmware_file: Path
    ):
        t = FakeTransport()
        # Device advertises only xfer_v1 — bridge refuses ota.
        info_line = (
            b'{"evt":"info","board":"m5stack-core2","version":"old","features":["xfer_v1"]}\n'
        )
        rc = await _patched_update(
            monkeypatch,
            transport=t,
            drainer_lines=[info_line],
            file_path=firmware_file,
            info_timeout_s=0.5,
        )
        assert rc == 5

    async def test_happy_path_exits_0(
        self, monkeypatch: pytest.MonkeyPatch, firmware_file: Path
    ):
        t = FakeTransport()
        info_line = (
            b'{"evt":"info","board":"m5stack-core2","version":"old","features":["xfer_v1","ota_v1"]}\n'
        )
        ready = b'{"evt":"ota_ready"}\n'
        committed = b'{"evt":"ota_committed"}\n'
        rc = await _patched_update(
            monkeypatch,
            transport=t,
            drainer_lines=[info_line, ready, committed],
            file_path=firmware_file,
            info_timeout_s=0.5,
        )
        assert rc == 0
        # Verify we sent begin + at least one data + commit.
        assert any(b'"ota_begin"' in s for s in t.sent)
        assert any(b'"ota_data"' in s for s in t.sent)
        assert any(b'"ota_commit"' in s for s in t.sent)

    async def test_no_feature_check_skips_gate(
        self, monkeypatch: pytest.MonkeyPatch, firmware_file: Path
    ):
        # Device that doesn't even send evt:info — should still push
        # when --no-feature-check is set.
        t = FakeTransport()
        ready = b'{"evt":"ota_ready"}\n'
        committed = b'{"evt":"ota_committed"}\n'
        rc = await _patched_update(
            monkeypatch,
            transport=t,
            drainer_lines=[ready, committed],
            info_first=False,  # device sends ota_ready in response to ota_begin
            file_path=firmware_file,
            require_feature=False,
            info_timeout_s=0.1,
        )
        assert rc == 0
