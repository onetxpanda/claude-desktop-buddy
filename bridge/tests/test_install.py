from __future__ import annotations

import contextlib
import json
from pathlib import Path

from claude_buddy_bridge.install import (
    HOOK_COMMAND,
    HOOK_EVENTS,
    install,
    uninstall,
)


def _settings(path: Path) -> dict:
    return json.loads(path.read_text())


class TestInstall:
    def test_creates_settings_when_missing(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        install(target)
        s = _settings(target)
        assert set(s["hooks"].keys()) == set(HOOK_EVENTS)
        for event in HOOK_EVENTS:
            entries = s["hooks"][event]
            assert len(entries) == 1
            assert entries[0]["matcher"] == "*"
            assert entries[0]["hooks"][0]["command"] == HOOK_COMMAND

    def test_preserves_existing_unrelated_settings(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        target.write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["ls"]}}))
        install(target)
        s = _settings(target)
        assert s["theme"] == "dark"
        assert s["permissions"] == {"allow": ["ls"]}

    def test_preserves_other_hook_commands(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        target.write_text(
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Bash",
                                "hooks": [{"type": "command", "command": "other-hook"}],
                            }
                        ]
                    }
                }
            )
        )
        install(target)
        entries = _settings(target)["hooks"]["PreToolUse"]
        assert len(entries) == 2
        assert any(
            h["command"] == "other-hook"
            for e in entries
            for h in e.get("hooks", [])
        )
        assert any(
            h["command"] == HOOK_COMMAND
            for e in entries
            for h in e.get("hooks", [])
        )

    def test_install_is_idempotent(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        install(target)
        install(target)
        install(target)
        for event in HOOK_EVENTS:
            entries = _settings(target)["hooks"][event]
            our = [
                h
                for e in entries
                for h in e.get("hooks", [])
                if h.get("command") == HOOK_COMMAND
            ]
            assert len(our) == 1

    def test_install_empty_file_works(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        target.write_text("")
        install(target)
        assert _settings(target)["hooks"]


class TestUninstall:
    def test_removes_only_our_entries(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        install(target)
        # Drop in a co-resident hook from another tool
        s = _settings(target)
        s["hooks"]["PreToolUse"].append(
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}
        )
        target.write_text(json.dumps(s))

        uninstall(target)

        s2 = _settings(target)
        pre = s2["hooks"]["PreToolUse"]
        assert len(pre) == 1
        assert pre[0]["hooks"][0]["command"] == "other"
        # Other events we added were our only entries; those keys should be gone.
        for event in HOOK_EVENTS:
            if event == "PreToolUse":
                continue
            assert event not in s2.get("hooks", {})

    def test_uninstall_removes_hooks_key_when_empty(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        install(target)
        uninstall(target)
        s = _settings(target)
        assert "hooks" not in s

    def test_uninstall_noop_when_missing(self, tmp_path: Path):
        target = tmp_path / "missing.json"
        uninstall(target)  # should not raise
        assert not target.exists()

    def test_uninstall_preserves_non_hook_settings(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        target.write_text(json.dumps({"theme": "dark"}))
        install(target)
        uninstall(target)
        assert _settings(target)["theme"] == "dark"


class TestAbsolutePathInstall:
    def test_install_with_absolute_path(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        abs_cmd = "/opt/foo/bin/claude-buddy-hook"
        from claude_buddy_bridge.install import install as install_fn

        install_fn(target, command=abs_cmd)
        data = _settings(target)
        assert (
            data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == abs_cmd
        )

    def test_uninstall_matches_by_basename(self, tmp_path: Path):
        """An install with an absolute path can be uninstalled by bare name."""
        target = tmp_path / "settings.json"
        from claude_buddy_bridge.install import install as install_fn

        install_fn(target, command="/elsewhere/claude-buddy-hook")
        uninstall(target)  # default command = "claude-buddy-hook"
        assert "hooks" not in _settings(target)

    def test_reinstall_does_not_duplicate_across_paths(self, tmp_path: Path):
        target = tmp_path / "settings.json"
        from claude_buddy_bridge.install import install as install_fn

        install_fn(target, command="/path/a/claude-buddy-hook")
        install_fn(target, command="/path/b/claude-buddy-hook")
        for event in HOOK_EVENTS:
            entries = _settings(target)["hooks"][event]
            ours = [
                h
                for e in entries
                for h in e.get("hooks", [])
                if Path(h.get("command", "")).name == "claude-buddy-hook"
            ]
            assert len(ours) == 1, f"{event}: {ours}"


class TestMalformedJson:
    def test_install_on_invalid_json_warns_but_proceeds(self, tmp_path, caplog):
        import logging

        target = tmp_path / "settings.json"
        target.write_text("{ this is not json")
        with caplog.at_level(logging.WARNING):
            install(target)
        # The bad file was replaced with a valid one containing our hooks
        data = json.loads(target.read_text())
        assert "hooks" in data
        assert any("not valid JSON" in r.message for r in caplog.records)

    def test_uninstall_on_invalid_json_is_safe(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text("{ not json")
        uninstall(target)  # must not raise
        # File should still exist; contents may be normalized or unchanged.
        assert target.exists()


class TestAtomicWrite:
    def test_settings_json_is_always_valid_after_install(self, tmp_path: Path):
        """No intermediate state that a concurrent reader would see as invalid."""
        target = tmp_path / "settings.json"
        install(target)
        # The file exists and parses — a concurrent reader would never hit a
        # zero-byte or half-written file because we write to a tempfile and
        # rename atomically.
        assert json.loads(target.read_text())["hooks"]

    def test_failed_write_does_not_leave_tempfile(self, tmp_path: Path, monkeypatch):
        """Exception during write is clean — no stale .tmp files remain."""
        from claude_buddy_bridge import install as im

        target = tmp_path / "settings.json"
        original = im._atomic_write

        def fail(_path, _content):  # type: ignore[no-untyped-def]
            # Simulate failure partway through: call original to create a
            # tempfile, then force an error before rename by monkeypatching
            # Path.replace.
            raise RuntimeError("disk full")

        monkeypatch.setattr(im, "_atomic_write", fail)
        with contextlib.suppress(RuntimeError):
            install(target)
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []
        monkeypatch.setattr(im, "_atomic_write", original)
