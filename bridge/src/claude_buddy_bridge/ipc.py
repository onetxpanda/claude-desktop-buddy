"""Unix-socket IPC between the bridge daemon and its helpers.

The server hosts one handler function that is invoked per newline-JSON request;
the client side (used by the hook shim) is deliberately fast-fail — it returns
``None`` on any network-level problem and never raises, so installing the hook
cannot degrade Claude Code behaviour when the daemon is unavailable.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path

Handler = Callable[[dict], Awaitable[dict]]


def default_socket_path() -> Path:
    """Return the platform-appropriate socket path."""

    xdg = os.environ.get("XDG_RUNTIME_DIR")
    if xdg:
        xdg_path = Path(xdg)
        if xdg_path.is_dir():
            return xdg_path / "claude-buddy.sock"
    return Path(f"/tmp/claude-buddy-{os.getuid()}.sock")


class IpcServer:
    def __init__(self, path: Path, handler: Handler) -> None:
        self._path = path
        self._handler = handler
        self._server: asyncio.base_events.Server | None = None

    @property
    def path(self) -> Path:
        return self._path

    async def start(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists() or self._path.is_symlink():
            with contextlib.suppress(FileNotFoundError):
                self._path.unlink()
        self._server = await asyncio.start_unix_server(
            self._on_client, path=str(self._path)
        )
        os.chmod(self._path, 0o600)

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._path.exists():
            with contextlib.suppress(FileNotFoundError):
                self._path.unlink()

    async def _on_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    return
                resp = await self._dispatch(line)
                writer.write((json.dumps(resp) + "\n").encode("utf-8"))
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            return
        finally:
            writer.close()
            with contextlib.suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()

    async def _dispatch(self, line: bytes) -> dict:
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"invalid JSON: {e}"}
        if not isinstance(req, dict):
            return {"ok": False, "error": "request must be a JSON object"}
        try:
            return await self._handler(req)
        except Exception as e:
            return {"ok": False, "error": f"handler error: {e}"}


class IpcClient:
    """Fast-fail client used by hooks. Returns ``None`` instead of raising."""

    def __init__(
        self,
        path: Path,
        *,
        connect_timeout_s: float = 0.05,
        total_budget_s: float = 0.1,
    ) -> None:
        self._path = path
        self._connect_timeout = connect_timeout_s
        self._total_budget = total_budget_s

    async def send(self, request: dict) -> dict | None:
        try:
            return await asyncio.wait_for(
                self._send_once(request), timeout=self._total_budget
            )
        except (TimeoutError, ConnectionRefusedError, FileNotFoundError, OSError):
            return None

    async def _send_once(self, request: dict) -> dict | None:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self._path)),
                timeout=self._connect_timeout,
            )
        except (TimeoutError, ConnectionRefusedError, FileNotFoundError, OSError):
            return None
        try:
            writer.write((json.dumps(request) + "\n").encode("utf-8"))
            await writer.drain()
            line = await reader.readline()
            if not line:
                return None
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                return None
        finally:
            writer.close()
            with contextlib.suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()
