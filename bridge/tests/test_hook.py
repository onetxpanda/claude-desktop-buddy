from __future__ import annotations

import io
import json
from typing import Any

import pytest

from claude_buddy_bridge import hook as hook_mod


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict] = []

    async def send(self, req: dict) -> dict | None:
        self.sent.append(req)
        return None if self.fail else {"ok": True}


@pytest.fixture
def fake_stdin(monkeypatch):
    def _set(payload: dict | str) -> None:
        data = payload if isinstance(payload, str) else json.dumps(payload)
        buf = io.BytesIO(data.encode("utf-8"))

        class _Stdin:
            buffer = buf

        monkeypatch.setattr(hook_mod.sys, "stdin", _Stdin())

    return _set


async def _run_with_client(client: FakeClient) -> int:
    return await hook_mod._run(client_factory=lambda: client)


class TestHookEventDispatch:
    async def test_pretooluse_builds_request(self, fake_stdin):
        fake_stdin(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "sess-1",
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
            }
        )
        client = FakeClient()
        assert await _run_with_client(client) == 0
        assert len(client.sent) == 1
        req = client.sent[0]
        assert req["op"] == "pretooluse"
        assert req["session_id"] == "sess-1"
        assert req["tool"] == "Bash"
        assert "ls -la" in req["hint"]
        assert isinstance(req["prompt_id"], str) and req["prompt_id"]

    async def test_posttooluse_builds_request(self, fake_stdin):
        fake_stdin(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "sess-1",
                "tool_name": "Bash",
            }
        )
        client = FakeClient()
        await _run_with_client(client)
        req = client.sent[0]
        assert req["op"] == "posttooluse"
        assert req["session_id"] == "sess-1"
        assert req["tool"] == "Bash"
        assert isinstance(req["pid"], int) and req["pid"] > 0

    async def test_user_prompt_submit_builds_request(self, fake_stdin):
        fake_stdin(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "sess-1",
                "prompt": "please fix the bug\nsecond line",
            }
        )
        client = FakeClient()
        await _run_with_client(client)
        assert client.sent[0]["op"] == "user_prompt_submit"
        assert client.sent[0]["text"].startswith("please fix")

    async def test_stop_forwards_transcript_path(self, fake_stdin):
        fake_stdin(
            {
                "hook_event_name": "Stop",
                "session_id": "sess-1",
                "transcript_path": "/tmp/fake.jsonl",
            }
        )
        client = FakeClient()
        await _run_with_client(client)
        req = client.sent[0]
        assert req["op"] == "stop"
        assert req["transcript_path"] == "/tmp/fake.jsonl"
        assert isinstance(req["pid"], int) and req["pid"] > 0

    async def test_session_start(self, fake_stdin):
        fake_stdin({"hook_event_name": "SessionStart", "session_id": "sess-1"})
        client = FakeClient()
        await _run_with_client(client)
        req = client.sent[0]
        assert req["op"] == "session_start"
        assert req["session_id"] == "sess-1"
        assert isinstance(req["pid"], int) and req["pid"] > 0

    async def test_session_end(self, fake_stdin):
        fake_stdin({"hook_event_name": "SessionEnd", "session_id": "sess-1"})
        client = FakeClient()
        await _run_with_client(client)
        req = client.sent[0]
        assert req["op"] == "session_end"
        assert req["session_id"] == "sess-1"
        assert isinstance(req["pid"], int) and req["pid"] > 0

    async def test_all_requests_include_parent_pid(self, fake_stdin, monkeypatch):
        monkeypatch.setattr(hook_mod, "_parent_pid", lambda: 4242)
        fake_stdin(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "sess-1",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            }
        )
        client = FakeClient()
        await _run_with_client(client)
        assert client.sent[0]["pid"] == 4242

    async def test_tmux_pane_propagated_when_env_set(self, fake_stdin, monkeypatch):
        monkeypatch.setenv("TMUX_PANE", "%7")
        fake_stdin(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "sess-1",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            }
        )
        client = FakeClient()
        await _run_with_client(client)
        assert client.sent[0]["tmux_pane"] == "%7"

    async def test_tmux_pane_empty_when_env_missing(self, fake_stdin, monkeypatch):
        monkeypatch.delenv("TMUX_PANE", raising=False)
        fake_stdin(
            {
                "hook_event_name": "SessionStart",
                "session_id": "sess-1",
            }
        )
        client = FakeClient()
        await _run_with_client(client)
        assert client.sent[0]["tmux_pane"] == ""


class TestHintExtraction:
    @pytest.mark.parametrize(
        "tool, input_, expected",
        [
            ("Bash", {"command": "git status"}, "git status"),
            ("Edit", {"file_path": "/tmp/foo.py"}, "/tmp/foo.py"),
            ("Write", {"file_path": "/tmp/foo.py"}, "/tmp/foo.py"),
            ("Read", {"file_path": "/tmp/foo.py"}, "/tmp/foo.py"),
            ("Grep", {"pattern": "needle"}, "needle"),
            ("Glob", {"pattern": "**/*.py"}, "**/*.py"),
            ("Unknown", {}, ""),
            ("Unknown", {"nothing": "useful"}, ""),
        ],
    )
    def test_extract_hint_cases(self, tool, input_, expected):
        assert hook_mod._extract_hint(tool, input_) == expected

    def test_hint_truncated_at_limit(self):
        long = "x" * 500
        assert len(hook_mod._extract_hint("Bash", {"command": long})) <= 80


class TestFailSafeBehavior:
    async def test_unknown_event_sends_nothing_exits_zero(self, fake_stdin):
        fake_stdin({"hook_event_name": "SomethingElse", "session_id": "sess-1"})
        client = FakeClient()
        assert await _run_with_client(client) == 0
        assert client.sent == []

    async def test_malformed_stdin_exits_zero(self, fake_stdin):
        fake_stdin("{not json")
        client = FakeClient()
        assert await _run_with_client(client) == 0
        assert client.sent == []

    async def test_missing_session_id_exits_zero(self, fake_stdin):
        fake_stdin({"hook_event_name": "PreToolUse", "tool_name": "Bash"})
        client = FakeClient()
        assert await _run_with_client(client) == 0
        assert client.sent == []

    async def test_client_failure_still_exits_zero(self, fake_stdin):
        fake_stdin(
            {
                "hook_event_name": "PreToolUse",
                "session_id": "sess-1",
                "tool_name": "Bash",
                "tool_input": {"command": "ls"},
            }
        )
        client = FakeClient(fail=True)
        assert await _run_with_client(client) == 0
        assert len(client.sent) == 1

    async def test_empty_stdin_exits_zero(self, fake_stdin):
        fake_stdin("")
        client = FakeClient()
        assert await _run_with_client(client) == 0


class TestMainEntrypoint:
    def test_main_returns_zero_on_handler_exception(self, fake_stdin, monkeypatch):
        fake_stdin({"hook_event_name": "PreToolUse", "session_id": "s"})

        def exploding_run(**_: Any) -> int:
            raise RuntimeError("boom")

        async def async_exploding(**_: Any) -> int:
            raise RuntimeError("boom")

        monkeypatch.setattr(hook_mod, "_run", async_exploding)
        assert hook_mod.main() == 0
