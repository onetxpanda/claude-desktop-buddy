"""User-facing ``claude-buddy`` CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
from pathlib import Path

from .install import (
    HOOK_COMMAND,
    default_settings_path,
    install,
    uninstall,
)
from .ipc import IpcClient, default_socket_path


def _cmd_install(_args: argparse.Namespace) -> int:
    resolved = shutil.which(HOOK_COMMAND)
    if resolved is None:
        print(
            f"error: `{HOOK_COMMAND}` is not on PATH. Install this package via\n"
            "pixi/pipx so the hook binary exists, then re-run this command.",
            file=sys.stderr,
        )
        return 1
    # Use the resolved absolute path so Claude Code can invoke the hook
    # regardless of the PATH its parent shell uses.
    path = install(command=resolved)
    print(f"Hook entries installed in {path}")
    print(f"Hook binary:               {resolved}")
    print("Run `claude-buddy start` in a terminal to launch the daemon.")
    return 0


def _cmd_uninstall(_args: argparse.Namespace) -> int:
    path = uninstall()
    if path.exists():
        print(f"Removed hook entries from {path}")
    else:
        print("No settings file to clean up.")
    return 0


def _cmd_start(_args: argparse.Namespace) -> int:
    from .daemon import main as daemon_main

    return daemon_main()


def _cmd_run(args: argparse.Namespace) -> int:
    from .wrapper import run as wrapper_run

    argv = list(args.child_argv) if args.child_argv else []
    if not argv:
        print("usage: claude-buddy run <command> [args...]", file=sys.stderr)
        return 2
    return wrapper_run(argv)


def _cmd_status(_args: argparse.Namespace) -> int:
    async def _go() -> dict | None:
        client = IpcClient(default_socket_path(), total_budget_s=1.0)
        return await client.send({"op": "status"})

    resp = asyncio.run(_go())
    if resp is None:
        print("Daemon unreachable. Is `claude-buddy start` running?")
        return 1
    print(json.dumps(resp, indent=2))
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    ok = True

    settings = default_settings_path()
    if settings.exists():
        try:
            data = json.loads(settings.read_text())
        except json.JSONDecodeError as e:
            print(f"[FAIL] {settings} is not valid JSON: {e}")
            ok = False
            data = None
        if data is not None:
            hooks = data.get("hooks") or {}
            installed_events = [
                e
                for e, entries in hooks.items()
                if isinstance(entries, list)
                and any(
                    Path(sub.get("command", "")).name == HOOK_COMMAND
                    for entry in entries
                    if isinstance(entry, dict)
                    for sub in entry.get("hooks", [])
                    if isinstance(sub, dict)
                )
            ]
            if installed_events:
                print(f"[ OK ] hook entries installed for: {', '.join(installed_events)}")
            else:
                print(f"[FAIL] no hook entries in {settings}. Run `claude-buddy install`.")
                ok = False
    else:
        print(f"[FAIL] {settings} does not exist. Run `claude-buddy install`.")
        ok = False

    if shutil.which(HOOK_COMMAND) is None:
        print(f"[FAIL] `{HOOK_COMMAND}` is not on PATH.")
        ok = False
    else:
        print(f"[ OK ] `{HOOK_COMMAND}` found on PATH.")

    sock = default_socket_path()
    if sock.exists():
        print(f"[ OK ] daemon socket present at {sock}")
    else:
        print(f"[WARN] daemon socket missing at {sock}. Run `claude-buddy start`.")

    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="claude-buddy",
        description="BLE buddy bridge for the Claude Code CLI.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("install", help="Merge hook entries into ~/.claude/settings.json")
    sub.add_parser("uninstall", help="Remove our hook entries from ~/.claude/settings.json")
    sub.add_parser("start", help="Run the bridge daemon in the foreground")
    sub.add_parser("status", help="Query the running daemon for current state")
    sub.add_parser("doctor", help="Diagnose install and connectivity")

    run_p = sub.add_parser(
        "run",
        help="Run a command under the PTY wrapper; buddy A-press approves prompts",
    )
    run_p.add_argument(
        "child_argv",
        nargs=argparse.REMAINDER,
        help="command and args to run (e.g. `claude -p some-prompt`)",
    )

    return p


DISPATCH = {
    "install": _cmd_install,
    "uninstall": _cmd_uninstall,
    "start": _cmd_start,
    "status": _cmd_status,
    "doctor": _cmd_doctor,
    "run": _cmd_run,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handler = DISPATCH[args.cmd]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
