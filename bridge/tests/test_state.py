from __future__ import annotations

import pytest

from claude_buddy_bridge.state import StateManager


@pytest.fixture
def clock():
    t = {"now": 1_700_000_000.0}

    def tick(delta: float = 0.0) -> float:
        t["now"] += delta
        return t["now"]

    def now() -> float:
        return t["now"]

    now.tick = tick  # type: ignore[attr-defined]
    return now


@pytest.fixture
def sm(clock):
    return StateManager(max_entries=5, now=clock)


class TestSessionLifecycle:
    def test_no_sessions_initially(self, sm):
        hb = sm.snapshot()
        assert hb.total == 0
        assert hb.running == 0
        assert hb.waiting == 0

    def test_session_start_counts_toward_total_and_running(self, sm):
        sm.session_start("s1")
        hb = sm.snapshot()
        assert hb.total == 1
        assert hb.running == 1

    def test_session_end_removes_from_total(self, sm):
        sm.session_start("s1")
        sm.session_end("s1")
        hb = sm.snapshot()
        assert hb.total == 0
        assert hb.running == 0

    def test_duplicate_session_start_is_idempotent(self, sm):
        sm.session_start("s1")
        sm.session_start("s1")
        assert sm.snapshot().total == 1

    def test_session_end_for_unknown_session_is_safe(self, sm):
        sm.session_end("never-seen")
        assert sm.snapshot().total == 0


class TestWaitingVsRunning:
    def test_pretooluse_marks_session_waiting(self, sm):
        sm.session_start("s1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        hb = sm.snapshot()
        assert hb.running == 0
        assert hb.waiting == 1
        assert hb.total == 1

    def test_posttooluse_returns_session_to_running(self, sm):
        sm.session_start("s1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        sm.post_tool_use("s1", tool="Bash")
        hb = sm.snapshot()
        assert hb.running == 1
        assert hb.waiting == 0

    def test_permission_decision_also_clears_waiting(self, sm):
        sm.session_start("s1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        resolved = sm.resolve_permission("p1", "once")
        assert resolved is not None
        assert resolved.session_id == "s1"
        assert sm.snapshot().waiting == 0

    def test_decision_for_unknown_prompt_returns_none(self, sm):
        assert sm.resolve_permission("nope", "deny") is None


class TestPromptQueue:
    def test_snapshot_includes_oldest_pending_prompt(self, sm):
        sm.session_start("s1")
        sm.session_start("s2")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        sm.pre_tool_use("s2", prompt_id="p2", tool="Edit", hint="foo.py")
        hb = sm.snapshot()
        assert hb.waiting == 2
        assert hb.prompt is not None
        assert hb.prompt.id == "p1"
        assert hb.prompt.tool == "Bash"

    def test_resolving_oldest_advances_to_next(self, sm):
        sm.session_start("s1")
        sm.session_start("s2")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        sm.pre_tool_use("s2", prompt_id="p2", tool="Edit", hint="foo.py")
        sm.resolve_permission("p1", "once")
        hb = sm.snapshot()
        assert hb.waiting == 1
        assert hb.prompt is not None
        assert hb.prompt.id == "p2"

    def test_no_prompt_in_snapshot_when_queue_empty(self, sm):
        sm.session_start("s1")
        hb = sm.snapshot()
        assert hb.prompt is None


class TestEntriesRingBuffer:
    def test_entries_populated_from_pretooluse(self, sm, clock):
        sm.session_start("s1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls -la")
        hb = sm.snapshot()
        assert len(hb.entries) == 1
        assert "Bash" in hb.entries[0]
        assert "ls -la" in hb.entries[0]

    def test_entries_capped_at_max(self, sm):
        sm.session_start("s1")
        for i in range(10):
            sm.pre_tool_use("s1", prompt_id=f"p{i}", tool="Bash", hint=f"cmd{i}")
        hb = sm.snapshot()
        assert len(hb.entries) == 5

    def test_entries_newest_first(self, sm):
        sm.session_start("s1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="first")
        sm.pre_tool_use("s1", prompt_id="p2", tool="Bash", hint="second")
        hb = sm.snapshot()
        assert "second" in hb.entries[0]
        assert "first" in hb.entries[1]


class TestTokens:
    def test_stop_accumulates_tokens(self, sm):
        sm.session_start("s1")
        sm.stop("s1", tokens_delta=500)
        sm.stop("s1", tokens_delta=300)
        hb = sm.snapshot()
        assert hb.tokens == 800
        assert hb.tokens_today == 800

    def test_negative_tokens_delta_ignored(self, sm):
        sm.session_start("s1")
        sm.stop("s1", tokens_delta=-50)
        assert sm.snapshot().tokens == 0


class TestMsgField:
    def test_msg_empty_when_nothing_happening(self, sm):
        assert sm.snapshot().msg == ""

    def test_msg_reflects_pending_prompt(self, sm):
        sm.session_start("s1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        assert "Bash" in sm.snapshot().msg


class TestPidTracking:
    def test_session_start_records_pid(self, sm):
        sm.session_start("s1", pid=1234)
        assert sm.sessions_with_pid() == [("s1", 1234)]

    def test_pretooluse_records_pid_when_session_missing(self, sm):
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls", pid=999)
        assert sm.sessions_with_pid() == [("s1", 999)]

    def test_pid_only_set_once_not_overwritten(self, sm):
        sm.session_start("s1", pid=1234)
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls", pid=5678)
        assert sm.sessions_with_pid() == [("s1", 1234)]

    def test_session_without_pid_not_listed(self, sm):
        sm.session_start("s1")
        assert sm.sessions_with_pid() == []

    def test_session_end_removes_from_pid_list(self, sm):
        sm.session_start("s1", pid=1234)
        sm.session_end("s1")
        assert sm.sessions_with_pid() == []

    def test_pid_is_ignored_when_none(self, sm):
        sm.session_start("s1", pid=None)
        assert sm.sessions_with_pid() == []
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls", pid=42)
        assert sm.sessions_with_pid() == [("s1", 42)]


class TestTmuxPaneRouting:
    def test_session_start_records_tmux_pane(self, sm):
        sm.session_start("s1", pid=100, tmux_pane="%3")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        resolved = sm.resolve_permission("p1", "once")
        assert resolved is not None
        assert resolved.tmux_pane == "%3"
        assert resolved.pid == 100
        assert resolved.session_id == "s1"

    def test_pretooluse_records_tmux_pane_when_session_unknown(self, sm):
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls", tmux_pane="%5")
        resolved = sm.resolve_permission("p1", "once")
        assert resolved is not None
        assert resolved.tmux_pane == "%5"

    def test_resolved_pane_is_none_when_not_set(self, sm):
        sm.session_start("s1", pid=200)
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls")
        resolved = sm.resolve_permission("p1", "once")
        assert resolved is not None
        assert resolved.tmux_pane is None
        assert resolved.pid == 200

    def test_pane_is_set_only_once(self, sm):
        sm.session_start("s1", tmux_pane="%1")
        sm.pre_tool_use("s1", prompt_id="p1", tool="Bash", hint="ls", tmux_pane="%9")
        resolved = sm.resolve_permission("p1", "once")
        assert resolved is not None
        assert resolved.tmux_pane == "%1"
