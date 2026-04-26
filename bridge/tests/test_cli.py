from __future__ import annotations

import json

import pytest

from claude_buddy_bridge import cli
from claude_buddy_bridge import install as install_mod


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        install_mod,
        "default_settings_path",
        lambda: tmp_path / ".claude" / "settings.json",
    )
    monkeypatch.setattr(
        cli,
        "default_settings_path",
        lambda: tmp_path / ".claude" / "settings.json",
    )
    return tmp_path


class TestInstallCommand:
    def test_install_creates_settings(self, fake_home, capsys):
        assert cli.main(["install"]) == 0
        path = fake_home / ".claude" / "settings.json"
        assert path.exists()
        data = json.loads(path.read_text())
        assert "hooks" in data

    def test_uninstall_after_install(self, fake_home, capsys):
        cli.main(["install"])
        assert cli.main(["uninstall"]) == 0
        data = json.loads((fake_home / ".claude" / "settings.json").read_text())
        assert "hooks" not in data


class TestDoctor:
    def test_doctor_fails_without_install(self, fake_home, capsys):
        rc = cli.main(["doctor"])
        captured = capsys.readouterr()
        assert rc == 1
        assert "does not exist" in captured.out or "no hook entries" in captured.out

    def test_doctor_after_install_reports_hooks(self, fake_home, capsys):
        cli.main(["install"])
        cli.main(["doctor"])
        captured = capsys.readouterr()
        assert "hook entries installed for" in captured.out
