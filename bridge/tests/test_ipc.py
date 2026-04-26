from __future__ import annotations

import asyncio
import contextlib
import tempfile
from pathlib import Path

import pytest

from claude_buddy_bridge.ipc import IpcClient, IpcServer, default_socket_path


@pytest.fixture
def sock_path() -> Path:
    # macOS caps AF_UNIX paths at 104 bytes, so pytest's tmp_path is too long.
    # Use a short mkdtemp under /tmp and clean up at end of test.
    d = Path(tempfile.mkdtemp(prefix="bud-", dir="/tmp"))
    try:
        yield d / "b.sock"
    finally:
        for p in d.iterdir():
            with contextlib.suppress(FileNotFoundError):
                p.unlink()
        with contextlib.suppress(OSError):
            d.rmdir()


async def _echo_handler(req: dict) -> dict:
    return {"ok": True, "echo": req}


class TestDefaultSocketPath:
    def test_uses_xdg_runtime_dir_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
        assert default_socket_path() == tmp_path / "claude-buddy.sock"

    def test_falls_back_to_tmp_when_xdg_missing(self, monkeypatch):
        monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
        path = default_socket_path()
        assert str(path).startswith("/tmp/claude-buddy-")
        assert str(path).endswith(".sock")


class TestServerClientRoundTrip:
    async def test_handler_receives_request_and_replies(self, sock_path):
        server = IpcServer(sock_path, _echo_handler)
        await server.start()
        try:
            client = IpcClient(sock_path)
            resp = await client.send({"op": "ping"})
            assert resp == {"ok": True, "echo": {"op": "ping"}}
        finally:
            await server.stop()

    async def test_server_cleans_up_socket_file_on_stop(self, sock_path):
        server = IpcServer(sock_path, _echo_handler)
        await server.start()
        assert sock_path.exists()
        await server.stop()
        assert not sock_path.exists()

    async def test_server_replaces_stale_socket_on_start(self, sock_path):
        sock_path.touch()
        server = IpcServer(sock_path, _echo_handler)
        await server.start()
        try:
            assert sock_path.exists()
        finally:
            await server.stop()


class TestClientFastFail:
    async def test_client_returns_none_when_server_absent(self, sock_path):
        client = IpcClient(sock_path)
        resp = await client.send({"op": "ping"})
        assert resp is None

    async def test_client_returns_none_when_socket_is_file_not_socket(self, sock_path):
        sock_path.touch()
        client = IpcClient(sock_path)
        resp = await client.send({"op": "ping"})
        assert resp is None

    async def test_client_respects_total_budget(self, sock_path):
        async def slow_handler(req: dict) -> dict:
            await asyncio.sleep(0.5)
            return {"ok": True}

        server = IpcServer(sock_path, slow_handler)
        await server.start()
        try:
            client = IpcClient(sock_path, total_budget_s=0.05)
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            resp = await client.send({"op": "ping"})
            elapsed = loop.time() - t0
            assert resp is None
            assert elapsed < 0.3
        finally:
            await server.stop()


class TestHandlerErrors:
    async def test_malformed_json_response_is_error(self, sock_path):
        server = IpcServer(sock_path, _echo_handler)
        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            writer.write(b"{not json\n")
            await writer.drain()
            line = await reader.readline()
            writer.close()
            await writer.wait_closed()
            import json

            obj = json.loads(line)
            assert obj["ok"] is False
            assert "invalid JSON" in obj["error"]
        finally:
            await server.stop()

    async def test_non_object_request_is_error(self, sock_path):
        server = IpcServer(sock_path, _echo_handler)
        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            writer.write(b"[]\n")
            await writer.drain()
            line = await reader.readline()
            writer.close()
            await writer.wait_closed()
            import json

            obj = json.loads(line)
            assert obj["ok"] is False
        finally:
            await server.stop()

    async def test_handler_exception_returns_error(self, sock_path):
        async def boom(req: dict) -> dict:
            raise RuntimeError("kaboom")

        server = IpcServer(sock_path, boom)
        await server.start()
        try:
            client = IpcClient(sock_path)
            resp = await client.send({"op": "x"})
            assert resp is not None
            assert resp["ok"] is False
            assert "kaboom" in resp["error"]
        finally:
            await server.stop()


class TestMultipleRequestsPerConnection:
    async def test_two_requests_same_connection(self, sock_path):
        server = IpcServer(sock_path, _echo_handler)
        await server.start()
        try:
            reader, writer = await asyncio.open_unix_connection(str(sock_path))
            import json

            writer.write(json.dumps({"a": 1}).encode() + b"\n")
            await writer.drain()
            r1 = json.loads(await reader.readline())
            writer.write(json.dumps({"a": 2}).encode() + b"\n")
            await writer.drain()
            r2 = json.loads(await reader.readline())
            writer.close()
            await writer.wait_closed()
            assert r1["echo"] == {"a": 1}
            assert r2["echo"] == {"a": 2}
        finally:
            await server.stop()
