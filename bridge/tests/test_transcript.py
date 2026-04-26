from __future__ import annotations

import json
from pathlib import Path

from claude_buddy_bridge.transcript import TranscriptReader, output_tokens_from_line


def _assistant_line(output_tokens: int, cache_read: int = 0) -> str:
    obj = {
        "type": "assistant",
        "message": {
            "id": "msg_x",
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
            "usage": {
                "input_tokens": 10,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
            },
        },
    }
    return json.dumps(obj) + "\n"


def _user_line() -> str:
    obj = {"type": "user", "message": {"role": "user", "content": "hello"}}
    return json.dumps(obj) + "\n"


class TestOutputTokensExtraction:
    def test_assistant_line_returns_output_tokens(self):
        assert output_tokens_from_line(_assistant_line(42)) == 42

    def test_user_line_returns_zero(self):
        assert output_tokens_from_line(_user_line()) == 0

    def test_invalid_json_returns_zero(self):
        assert output_tokens_from_line("{not json\n") == 0

    def test_missing_usage_returns_zero(self):
        line = json.dumps({"type": "assistant", "message": {"role": "assistant"}})
        assert output_tokens_from_line(line) == 0

    def test_empty_line_returns_zero(self):
        assert output_tokens_from_line("") == 0


class TestTranscriptReader:
    def test_returns_zero_for_missing_file(self, tmp_path: Path):
        r = TranscriptReader(tmp_path / "nope.jsonl")
        assert r.pull_delta() == 0

    def test_counts_first_assistant_turn(self, tmp_path: Path):
        p = tmp_path / "t.jsonl"
        p.write_text(_user_line() + _assistant_line(100))
        r = TranscriptReader(p)
        assert r.pull_delta() == 100

    def test_incremental_only_counts_new_lines(self, tmp_path: Path):
        p = tmp_path / "t.jsonl"
        p.write_text(_user_line() + _assistant_line(100))
        r = TranscriptReader(p)
        assert r.pull_delta() == 100
        with p.open("a") as f:
            f.write(_user_line())
            f.write(_assistant_line(50))
        assert r.pull_delta() == 50
        assert r.pull_delta() == 0

    def test_partial_line_waits_for_newline(self, tmp_path: Path):
        p = tmp_path / "t.jsonl"
        p.write_text(_assistant_line(200))
        partial = _assistant_line(300).rstrip("\n")
        with p.open("a") as f:
            f.write(partial)
        r = TranscriptReader(p)
        assert r.pull_delta() == 200
        with p.open("a") as f:
            f.write("\n")
        assert r.pull_delta() == 300

    def test_file_truncation_resets_offset(self, tmp_path: Path):
        p = tmp_path / "t.jsonl"
        p.write_text(_assistant_line(50) + _assistant_line(100) + _assistant_line(200))
        r = TranscriptReader(p)
        assert r.pull_delta() == 350
        # A new session starts: file replaced with shorter content.
        p.write_text(_assistant_line(20))
        assert r.pull_delta() == 20
