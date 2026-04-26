import json

import pytest

from claude_buddy_bridge.protocol import (
    Ack,
    Heartbeat,
    HostCommand,
    Info,
    LineReader,
    OtaAck,
    OtaCommitted,
    OtaError,
    OtaProgress,
    OtaReady,
    PermissionDecision,
    Prompt,
    ProtocolError,
    TimeSync,
    TurnEvent,
    decode_device_line,
)


class TestParserTolerance:
    """Phase C: parser ignores unknown shapes so future protocol
    additions on the device side don't require coordinated bridge bumps."""

    def test_unknown_evt_returns_none(self):
        assert decode_device_line(b'{"evt":"some_future_thing"}\n') is None

    def test_unknown_cmd_returns_none(self):
        assert decode_device_line(b'{"cmd":"some_future_cmd","x":1}\n') is None

    def test_no_cmd_evt_or_ack_returns_none(self):
        assert decode_device_line(b'{"random":"shape"}\n') is None

    def test_malformed_json_still_raises(self):
        with pytest.raises(ProtocolError, match="invalid JSON"):
            decode_device_line(b"{not json\n")

    def test_known_shape_with_bad_fields_still_raises(self):
        # ack is a known shape — malformed should be loud.
        with pytest.raises(ProtocolError, match="malformed ack"):
            decode_device_line(b'{"ack":"foo"}\n')  # missing ok


class TestEvtDecoding:
    def test_info(self):
        msg = decode_device_line(
            b'{"evt":"info","board":"m5stack-core2","version":"x@abc1234","features":["xfer_v1","ota_v1"]}\n'
        )
        assert msg == Info(
            board="m5stack-core2",
            version="x@abc1234",
            features=("xfer_v1", "ota_v1"),
        )

    def test_ota_ready(self):
        assert decode_device_line(b'{"evt":"ota_ready"}\n') == OtaReady()

    def test_ota_ack(self):
        assert decode_device_line(b'{"evt":"ota_ack","seq":31}\n') == OtaAck(seq=31)

    def test_ota_progress(self):
        assert decode_device_line(b'{"evt":"ota_progress","pct":42}\n') == OtaProgress(pct=42)

    def test_ota_committed(self):
        assert decode_device_line(b'{"evt":"ota_committed"}\n') == OtaCommitted()

    def test_ota_error(self):
        assert decode_device_line(
            b'{"evt":"ota_error","msg":"sha mismatch"}\n'
        ) == OtaError(msg="sha mismatch")


class TestHeartbeatEncoding:
    def test_minimal_heartbeat_omits_prompt(self):
        line = Heartbeat().to_json_line()
        assert line.endswith(b"\n")
        obj = json.loads(line)
        assert obj == {
            "total": 0,
            "running": 0,
            "waiting": 0,
            "msg": "",
            "entries": [],
            "tokens": 0,
            "tokens_today": 0,
        }
        assert "prompt" not in obj

    def test_heartbeat_with_prompt_includes_prompt_object(self):
        hb = Heartbeat(
            total=1,
            running=0,
            waiting=1,
            msg="approve: Bash",
            entries=["10:42 git push"],
            tokens=100,
            tokens_today=50,
            prompt=Prompt(id="req_1", tool="Bash", hint="ls"),
        )
        obj = json.loads(hb.to_json_line())
        assert obj["prompt"] == {"id": "req_1", "tool": "Bash", "hint": "ls"}
        assert obj["entries"] == ["10:42 git push"]
        assert obj["tokens_today"] == 50

    def test_heartbeat_encoding_captures_entries_snapshot(self):
        entries = ["a", "b"]
        hb = Heartbeat(entries=entries)
        entries.append("c")
        obj = json.loads(hb.to_json_line())
        assert obj["entries"] == ["a", "b"]


class TestTurnEventEncoding:
    def test_turn_event_emits_evt_turn(self):
        t = TurnEvent(role="assistant", content=[{"type": "text", "text": "hi"}])
        obj = json.loads(t.to_json_line())
        assert obj == {
            "evt": "turn",
            "role": "assistant",
            "content": [{"type": "text", "text": "hi"}],
        }


class TestTimeSyncEncoding:
    def test_time_sync_emits_two_element_array(self):
        ts = TimeSync(epoch=1775731234, tz_offset_seconds=-25200)
        obj = json.loads(ts.to_json_line())
        assert obj == {"time": [1775731234, -25200]}


class TestHostCommandEncoding:
    def test_status_command(self):
        obj = json.loads(HostCommand("status").to_json_line())
        assert obj == {"cmd": "status"}

    def test_owner_command_with_extra(self):
        obj = json.loads(HostCommand("owner", {"name": "Felix"}).to_json_line())
        assert obj == {"cmd": "owner", "name": "Felix"}

    def test_name_command(self):
        obj = json.loads(HostCommand("name", {"name": "Clawd"}).to_json_line())
        assert obj == {"cmd": "name", "name": "Clawd"}


class TestDecodeDeviceLine:
    def test_decode_permission_once(self):
        msg = decode_device_line(b'{"cmd":"permission","id":"req_1","decision":"once"}')
        assert msg == PermissionDecision(id="req_1", decision="once")

    def test_decode_permission_deny(self):
        msg = decode_device_line('{"cmd":"permission","id":"r","decision":"deny"}')
        assert msg == PermissionDecision(id="r", decision="deny")

    def test_decode_simple_ack(self):
        msg = decode_device_line(b'{"ack":"owner","ok":true}')
        assert msg == Ack(ack="owner", ok=True, n=0, error=None, data=None)

    def test_decode_ack_with_data(self):
        msg = decode_device_line(
            b'{"ack":"status","ok":true,"data":{"name":"Clawd","sec":true}}'
        )
        assert isinstance(msg, Ack)
        assert msg.data == {"name": "Clawd", "sec": True}
        assert msg.ok is True
        assert msg.ack == "status"

    def test_decode_failed_ack_with_error(self):
        msg = decode_device_line(b'{"ack":"chunk","ok":false,"error":"disk full"}')
        assert msg == Ack(ack="chunk", ok=False, n=0, error="disk full", data=None)

    def test_decode_ack_with_byte_counter(self):
        msg = decode_device_line(b'{"ack":"chunk","ok":true,"n":128}')
        assert msg == Ack(ack="chunk", ok=True, n=128)

    def test_decode_invalid_json_raises(self):
        with pytest.raises(ProtocolError, match="invalid JSON"):
            decode_device_line(b"{not json")

    def test_decode_empty_line_raises(self):
        with pytest.raises(ProtocolError, match="empty"):
            decode_device_line(b"")

    def test_decode_whitespace_only_raises(self):
        with pytest.raises(ProtocolError, match="empty"):
            decode_device_line(b"   \n")

    def test_decode_non_object_raises(self):
        with pytest.raises(ProtocolError, match="expected object"):
            decode_device_line(b"[]")

    def test_decode_unknown_device_cmd_returns_none(self):
        # Phase C: unknown device cmd: is tolerated (parser returns
        # None) so future protocol additions don't require a
        # coordinated bridge bump. Was previously: raises ProtocolError.
        assert decode_device_line(b'{"cmd":"mystery"}') is None

    def test_decode_malformed_permission_bad_decision(self):
        with pytest.raises(ProtocolError, match="malformed permission"):
            decode_device_line(b'{"cmd":"permission","id":"x","decision":"maybe"}')

    def test_decode_malformed_permission_missing_id(self):
        with pytest.raises(ProtocolError, match="malformed permission"):
            decode_device_line(b'{"cmd":"permission","decision":"once"}')

    def test_decode_unrecognized_shape_returns_none(self):
        # Phase C: unrecognized shapes are tolerated (return None).
        assert decode_device_line(b'{"hello":"world"}') is None

    def test_decode_malformed_ack_missing_ok(self):
        with pytest.raises(ProtocolError, match="malformed ack"):
            decode_device_line(b'{"ack":"status"}')


class TestLineReader:
    def test_single_complete_line(self):
        r = LineReader()
        assert r.feed(b'{"a":1}\n') == [b'{"a":1}']

    def test_partial_then_complete(self):
        r = LineReader()
        assert r.feed(b'{"a') == []
        assert r.feed(b'":1}\n') == [b'{"a":1}']

    def test_multiple_lines_in_one_chunk(self):
        r = LineReader()
        assert r.feed(b'{"a":1}\n{"b":2}\n') == [b'{"a":1}', b'{"b":2}']

    def test_trailing_partial_kept_for_next(self):
        r = LineReader()
        assert r.feed(b'{"a":1}\n{"b') == [b'{"a":1}']
        assert r.feed(b'":2}\n') == [b'{"b":2}']

    def test_empty_feed_yields_nothing(self):
        r = LineReader()
        assert r.feed(b"") == []
