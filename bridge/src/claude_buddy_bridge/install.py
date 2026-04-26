"""Safe merge of our hook entries into Claude Code's settings.json."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

HOOK_EVENTS: tuple[str, ...] = (
    "PreToolUse",
    "PostToolUse",
    "UserPromptSubmit",
    "Stop",
    "SessionStart",
    "SessionEnd",
)

HOOK_COMMAND = "claude-buddy-hook"


def default_settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        text = path.read_text()
    except OSError:
        return {}
    if not text.strip():
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        log.warning(
            "%s is not valid JSON (%s); treating as empty. Re-run `claude-buddy "
            "install` after fixing the file to restore your other settings.",
            path,
            e,
        )
        return {}


def _atomic_write(path: Path, content: str) -> None:
    """Write `content` to `path` atomically so a concurrent reader never
    sees a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _matches_command(sub: object, command: str) -> bool:
    """True if `sub` is one of our hook entries.

    Matches on either the exact command string or on basename, so a user who
    installed with an absolute path (e.g. ``/opt/.../claude-buddy-hook``) can
    still be uninstalled with the default name and vice versa.
    """
    if not isinstance(sub, dict):
        return False
    existing = sub.get("command")
    if not isinstance(existing, str):
        return False
    if existing == command:
        return True
    return Path(existing).name == Path(command).name


def _event_has_our_entry(entries: list, command: str) -> bool:
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        subs = entry.get("hooks")
        if not isinstance(subs, list):
            continue
        if any(_matches_command(s, command) for s in subs):
            return True
    return False


def install(
    path: Path | None = None,
    *,
    command: str = HOOK_COMMAND,
    events: tuple[str, ...] = HOOK_EVENTS,
) -> Path:
    """Merge our hook entries into settings.json. Idempotent."""

    target = path or default_settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    settings = _load(target)
    hooks = settings.setdefault("hooks", {})
    for event in events:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            continue
        if _event_has_our_entry(entries, command):
            continue
        entries.append(
            {
                "matcher": "*",
                "hooks": [{"type": "command", "command": command}],
            }
        )
    _atomic_write(target, json.dumps(settings, indent=2) + "\n")
    return target


def uninstall(
    path: Path | None = None,
    *,
    command: str = HOOK_COMMAND,
) -> Path:
    """Remove only our hook entries, preserving everything else."""

    target = path or default_settings_path()
    if not target.exists():
        return target
    settings = _load(target)
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return target

    for event in list(hooks.keys()):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        new_entries: list = []
        for entry in entries:
            if not isinstance(entry, dict):
                new_entries.append(entry)
                continue
            subs = entry.get("hooks")
            if isinstance(subs, list):
                kept_subs = [s for s in subs if not _matches_command(s, command)]
                if not kept_subs:
                    continue  # drop entry whose only hook was ours
                entry = {**entry, "hooks": kept_subs}
            new_entries.append(entry)
        if new_entries:
            hooks[event] = new_entries
        else:
            del hooks[event]

    if not hooks:
        settings.pop("hooks", None)
    _atomic_write(target, json.dumps(settings, indent=2) + "\n")
    return target
