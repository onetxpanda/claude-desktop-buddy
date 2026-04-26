"""Wire protocol for the anthropics/claude-desktop-buddy BLE device.

All traffic is UTF-8 JSON, one object per line, terminated with ``\\n``.
See https://github.com/anthropics/claude-desktop-buddy/blob/main/REFERENCE.md
for the upstream protocol definition.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Decision = Literal["once", "deny"]


@dataclass(frozen=True)
class Prompt:
    """A pending tool-use permission request embedded in a heartbeat."""

    id: str
    tool: str
    hint: str = ""


@dataclass
class Heartbeat:
    """Status snapshot pushed to the device on change or every ~10s."""

    total: int = 0
    running: int = 0
    waiting: int = 0
    msg: str = ""
    entries: list[str] = field(default_factory=list)
    tokens: int = 0
    tokens_today: int = 0
    prompt: Prompt | None = None

    def __post_init__(self) -> None:
        self.entries = list(self.entries)

    def to_json_line(self) -> bytes:
        d: dict[str, Any] = {
            "total": self.total,
            "running": self.running,
            "waiting": self.waiting,
            "msg": self.msg,
            "entries": list(self.entries),
            "tokens": self.tokens,
            "tokens_today": self.tokens_today,
        }
        if self.prompt is not None:
            d["prompt"] = {
                "id": self.prompt.id,
                "tool": self.prompt.tool,
                "hint": self.prompt.hint,
            }
        return (json.dumps(d, separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True)
class TurnEvent:
    """One-shot event fired after each completed model turn."""

    role: str
    content: list[dict[str, Any]]

    def to_json_line(self) -> bytes:
        d = {"evt": "turn", "role": self.role, "content": self.content}
        return (json.dumps(d, separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True)
class TimeSync:
    """Sent on connect: [epoch_seconds, tz_offset_seconds]."""

    epoch: int
    tz_offset_seconds: int

    def to_json_line(self) -> bytes:
        d = {"time": [self.epoch, self.tz_offset_seconds]}
        return (json.dumps(d, separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True)
class HostCommand:
    """Host-to-device command. Requires a matching ack from the device."""

    cmd: str
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json_line(self) -> bytes:
        d: dict[str, Any] = {"cmd": self.cmd}
        d.update(self.extra)
        return (json.dumps(d, separators=(",", ":")) + "\n").encode("utf-8")


@dataclass(frozen=True)
class PermissionDecision:
    """Device-initiated approval or denial of a pending prompt."""

    id: str
    decision: Decision


@dataclass(frozen=True)
class Ack:
    """Device response to a host command."""

    ack: str
    ok: bool
    n: int = 0
    error: str | None = None
    data: dict[str, Any] | None = None


# Device-initiated events emitted on connect or during a flow like OTA.
# All `evt:*` shapes are device → bridge fire-and-forget; the bridge is
# free to ignore unknown ones (decode_device_line returns None).
@dataclass(frozen=True)
class Info:
    """evt:info — sent once on every BLE connection.

    Bridge reads `version` to decide whether OTA is needed and `features`
    to gate which cmd:* it can safely send. xfer_v1 = file-transfer
    protocol from xfer.h; ota_v1 = the BLE-driven OTA state machine
    introduced in Phase C.
    """

    board: str
    version: str
    features: tuple[str, ...] = ()


@dataclass(frozen=True)
class OtaReady:
    """evt:ota_ready — Update.begin() succeeded; bridge may start sending ota_data."""


@dataclass(frozen=True)
class OtaAck:
    """evt:ota_ack — periodic ack of received chunks (every 32nd by default)."""

    seq: int


@dataclass(frozen=True)
class OtaProgress:
    """evt:ota_progress — 0-100 percent received so far."""

    pct: int


@dataclass(frozen=True)
class OtaCommitted:
    """evt:ota_committed — Update.end(true) succeeded; device about to reboot."""


@dataclass(frozen=True)
class OtaAborted:
    """evt:ota_aborted — device acknowledged a cmd:ota_abort."""


@dataclass(frozen=True)
class OtaError:
    """evt:ota_error — flow failed; state machine is back to Idle."""

    msg: str


DeviceMessage = (
    PermissionDecision
    | Ack
    | Info
    | OtaReady
    | OtaAck
    | OtaProgress
    | OtaCommitted
    | OtaAborted
    | OtaError
)


class ProtocolError(ValueError):
    """Raised when a line from the device cannot be parsed."""


def decode_device_line(line: bytes | str) -> DeviceMessage | None:
    """Decode a single newline-stripped JSON line received from the device.

    Returns None for shapes we don't recognize, so future protocol
    additions on the device side don't require a coordinated bridge bump.
    Callers should skip None lines (treat as a debug log signal).
    Raises ProtocolError only for malformed JSON or known-shape-but-bad-fields.
    """

    if isinstance(line, bytes):
        line = line.decode("utf-8")
    line = line.strip()
    if not line:
        raise ProtocolError("empty line")
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as e:
        raise ProtocolError(f"invalid JSON: {e}") from e
    if not isinstance(obj, dict):
        raise ProtocolError(f"expected object, got {type(obj).__name__}")

    if "cmd" in obj:
        cmd = obj["cmd"]
        if cmd == "permission":
            pid = obj.get("id")
            decision = obj.get("decision")
            if not isinstance(pid, str) or decision not in ("once", "deny"):
                raise ProtocolError(f"malformed permission: {obj}")
            return PermissionDecision(id=pid, decision=decision)
        # Unknown device cmd: → ignore (parser tolerance, see module docstring).
        return None

    if "ack" in obj:
        ack = obj.get("ack")
        ok = obj.get("ok")
        if not isinstance(ack, str) or not isinstance(ok, bool):
            raise ProtocolError(f"malformed ack: {obj}")
        n_raw = obj.get("n", 0)
        n = int(n_raw) if isinstance(n_raw, int) else 0
        error = obj.get("error")
        data = obj.get("data")
        return Ack(
            ack=ack,
            ok=ok,
            n=n,
            error=error if isinstance(error, str) else None,
            data=data if isinstance(data, dict) else None,
        )

    if "evt" in obj:
        evt = obj["evt"]
        if evt == "info":
            board = obj.get("board")
            version = obj.get("version")
            features = obj.get("features", [])
            if not isinstance(board, str) or not isinstance(version, str):
                raise ProtocolError(f"malformed info: {obj}")
            feats = tuple(f for f in features if isinstance(f, str))
            return Info(board=board, version=version, features=feats)
        if evt == "ota_ready":
            return OtaReady()
        if evt == "ota_ack":
            seq = obj.get("seq")
            if not isinstance(seq, int):
                raise ProtocolError(f"malformed ota_ack: {obj}")
            return OtaAck(seq=seq)
        if evt == "ota_progress":
            pct = obj.get("pct")
            if not isinstance(pct, int):
                raise ProtocolError(f"malformed ota_progress: {obj}")
            return OtaProgress(pct=pct)
        if evt == "ota_committed":
            return OtaCommitted()
        if evt == "ota_aborted":
            return OtaAborted()
        if evt == "ota_error":
            msg = obj.get("msg", "")
            return OtaError(msg=msg if isinstance(msg, str) else "")
        # Unknown evt: → ignore.
        return None

    # Unknown shape entirely → ignore.
    return None


class LineReader:
    """Accumulates raw bytes and yields complete newline-terminated lines."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        if not data:
            return []
        self._buf.extend(data)
        out: list[bytes] = []
        while True:
            idx = self._buf.find(b"\n")
            if idx < 0:
                break
            out.append(bytes(self._buf[:idx]))
            del self._buf[: idx + 1]
        return out
