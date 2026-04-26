"""Opt-in PTY wrapper so a buddy A-press can approve a ``claude`` tool call.

``claude-buddy run claude`` forks ``claude`` into a pseudo-terminal, passes
stdin and stdout through transparently, and long-polls the daemon for
approval decisions. When a decision arrives it writes ``y\\n`` into the
child's stdin — the equivalent of the user having typed ``y`` in the
terminal. If the daemon is down, the buddy is disconnected, or the user
types ``y`` first, the wrapper does nothing and ``claude`` behaves exactly
as it would without this wrapper.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import pty
import signal
import struct  # noqa: F401  — struct is used by termios ioctl buffers implicitly
import sys
import termios
import tty
from collections.abc import Callable, Sequence
from pathlib import Path

from .ipc import default_socket_path

log = logging.getLogger(__name__)

# In raw mode (set by tty.setraw on the parent stdin) the keyboard's Enter
# key sends ``\r``, not ``\n``. The TUI on the other side of the pty matches
# what the keyboard actually delivers, so we need to inject CR to look like a
# real Enter press; ``\n`` would be a different byte and would not commit.
_INJECT_ON_APPROVE = b"y\r"
_POLL_TIMEOUT_S = 30.0


def _forward_winsize(master_fd: int) -> None:
    """Propagate the current terminal size to the pty slave."""
    try:
        size = fcntl.ioctl(sys.stdin.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, size)
    except OSError:
        pass


async def _ipc_subscribe(
    child_pid: int,
    sock_path: Path,
    inject: Callable[[bytes], None],
    stop: asyncio.Event,
    *,
    poll_timeout_s: float = _POLL_TIMEOUT_S,
    reconnect_delay_s: float = 2.0,
) -> None:
    """Long-poll the daemon for decisions; inject `y\\r` on each 'once'."""
    registered = False
    while not stop.is_set():
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(sock_path)),
                timeout=1.0,
            )
        except (OSError, TimeoutError):
            await _sleep_interruptible(reconnect_delay_s, stop)
            continue

        try:
            if not registered:
                writer.write(
                    (
                        json.dumps({"op": "register_wrapper", "child_pid": child_pid})
                        + "\n"
                    ).encode()
                )
                await writer.drain()
                line = await asyncio.wait_for(reader.readline(), timeout=2.0)
                if not line:
                    continue
                resp = json.loads(line)
                if not resp.get("ok"):
                    log.warning("daemon rejected register_wrapper: %s", resp)
                    return
                registered = True

            writer.write(
                (
                    json.dumps(
                        {
                            "op": "poll_wrapper",
                            "child_pid": child_pid,
                            "timeout": poll_timeout_s,
                        }
                    )
                    + "\n"
                ).encode()
            )
            await writer.drain()
            line = await asyncio.wait_for(
                reader.readline(), timeout=poll_timeout_s + 5.0
            )
            if not line:
                registered = False  # daemon likely restarted
                continue
            resp = json.loads(line)
            decisions = resp.get("decisions", []) or []
            if decisions:
                log.info("wrapper: poll returned %d decision(s): %s", len(decisions), decisions)
            for d in decisions:
                if d.get("decision") == "once":
                    inject(_INJECT_ON_APPROVE)
                else:
                    log.info(
                        "wrapper: received decision %s (no inject)", d.get("decision")
                    )
        except (
            ConnectionResetError,
            BrokenPipeError,
            TimeoutError,
            OSError,
            json.JSONDecodeError,
        ) as e:
            log.debug("ipc loop hiccup: %s", e)
            registered = False
        finally:
            writer.close()
            with contextlib.suppress(ConnectionResetError, BrokenPipeError):
                await writer.wait_closed()


async def _sleep_interruptible(seconds: float, stop: asyncio.Event) -> None:
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop.wait(), timeout=seconds)


async def _parent_loop(
    child_pid: int, master_fd: int, stdin_fd: int, sock_path: Path
) -> int:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    stdout_fd = sys.stdout.fileno()

    def read_stdin() -> None:
        try:
            data = os.read(stdin_fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            stop.set()
            return
        if not data:
            stop.set()
            return
        try:
            os.write(master_fd, data)
        except OSError:
            stop.set()

    def read_master() -> None:
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            stop.set()
            return
        if not data:
            stop.set()
            return
        try:
            os.write(stdout_fd, data)
        except OSError:
            stop.set()

    loop.add_reader(stdin_fd, read_stdin)
    loop.add_reader(master_fd, read_master)
    with contextlib.suppress(NotImplementedError, ValueError):
        loop.add_signal_handler(signal.SIGWINCH, lambda: _forward_winsize(master_fd))

    def inject(payload: bytes) -> None:
        try:
            n = os.write(master_fd, payload)
            log.info("wrapper: injected %d bytes (%r) into master_fd=%d", n, payload, master_fd)
        except OSError as e:
            log.warning("wrapper: inject failed: %s", e)

    log.info("wrapper: parent loop starting (child_pid=%d, master_fd=%d)", child_pid, master_fd)
    ipc_task = asyncio.create_task(_ipc_subscribe(child_pid, sock_path, inject, stop))

    async def wait_child() -> int:
        while not stop.is_set():
            try:
                wpid, status = os.waitpid(child_pid, os.WNOHANG)
            except ChildProcessError:
                return 0
            if wpid != 0:
                return status
            await asyncio.sleep(0.1)
        return 0

    child_task = asyncio.create_task(wait_child())
    stop_task = asyncio.create_task(stop.wait())
    _done, pending = await asyncio.wait(
        {child_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
    )
    stop.set()

    for task in pending:
        task.cancel()
    ipc_task.cancel()
    for task in (ipc_task, *pending):
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    with contextlib.suppress(ValueError, OSError):
        loop.remove_reader(stdin_fd)
    with contextlib.suppress(ValueError, OSError):
        loop.remove_reader(master_fd)
    with contextlib.suppress(NotImplementedError, ValueError):
        loop.remove_signal_handler(signal.SIGWINCH)

    # Reap child if it's still running (e.g. stdin closed but child kept going).
    status = 0
    if child_task.done():
        status = child_task.result()
    else:
        with contextlib.suppress(ChildProcessError):
            wpid, status = os.waitpid(child_pid, os.WNOHANG)
            if wpid == 0:
                os.kill(child_pid, signal.SIGTERM)
                wpid, status = os.waitpid(child_pid, 0)

    with contextlib.suppress(OSError):
        os.close(master_fd)

    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return 128 + os.WTERMSIG(status)
    return 0


def _configure_logging() -> None:
    log_path = os.environ.get("CLAUDE_BUDDY_WRAPPER_LOG")
    if not log_path:
        return
    # Avoid double-handlers if run() is invoked multiple times in the same process.
    root = logging.getLogger()
    if any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == os.path.abspath(log_path)
        for h in root.handlers
    ):
        return
    handler = logging.FileHandler(log_path)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    log.info("=== wrapper logging started (pid=%d) ===", os.getpid())


def run(argv: Sequence[str], sock_path: Path | None = None) -> int:
    """Run argv under a PTY wrapper that forwards IO and listens for decisions."""
    _configure_logging()
    if not argv:
        sys.stderr.write("claude-buddy run: command required\n")
        return 2

    sock_path = sock_path or default_socket_path()

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        # Non-interactive invocation: wrapping a pty would change observable
        # behaviour (color codes, prompt styling), so just exec directly.
        try:
            os.execvp(argv[0], list(argv))
        except FileNotFoundError:
            sys.stderr.write(f"claude-buddy: command not found: {argv[0]}\n")
            return 127
        return 0  # pragma: no cover — unreachable after execvp

    fd_in = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd_in)
    try:
        pid, master_fd = pty.fork()
    except OSError as e:
        sys.stderr.write(f"claude-buddy: pty.fork failed: {e}\n")
        return 1

    if pid == 0:
        # Child process: inherits the slave fd as stdin/stdout/stderr.
        try:
            os.execvp(argv[0], list(argv))
        except FileNotFoundError:
            sys.stderr.write(f"claude-buddy: command not found: {argv[0]}\n")
            os._exit(127)
        except OSError as e:
            sys.stderr.write(f"claude-buddy: exec failed: {e}\n")
            os._exit(126)
        os._exit(1)  # pragma: no cover

    try:
        tty.setraw(fd_in)
        _forward_winsize(master_fd)
        return asyncio.run(_parent_loop(pid, master_fd, fd_in, sock_path))
    finally:
        termios.tcsetattr(fd_in, termios.TCSADRAIN, old_attrs)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        sys.stderr.write("usage: claude-buddy run <command> [args...]\n")
        return 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
