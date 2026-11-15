"""Engine.IO v3 xhr-polling encode/decode (as used by scorebot-lb)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

# engine.io-client `yeast` (EIO=3 `t=` query). Not unix milliseconds.
_YEAST_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"


def yeast_encode(num: int) -> str:
    n = max(0, int(num))
    out: list[str] = []
    base = len(_YEAST_ALPHABET)
    while True:
        out.append(_YEAST_ALPHABET[n % base])
        n //= base
        if n <= 0:
            break
    return "".join(reversed(out))


class Yeast:
    def __init__(self) -> None:
        self._seed = 0
        self._prev = ""

    def next(self, now_ms: int | None = None) -> str:
        encoded = yeast_encode(int(time.time() * 1000) if now_ms is None else now_ms)
        if encoded != self._prev:
            self._seed = 0
            self._prev = encoded
            return encoded
        token = encoded + "." + yeast_encode(self._seed)
        self._seed += 1
        return token


_yeast = Yeast()


def eio_t(now_ms: int | None = None) -> str:
    return _yeast.next(now_ms)


def decode_payload(data: bytes) -> list[str]:
    if not data:
        return []
    if data[:1] != b"\x00":
        text = data.decode("utf-8", "replace")
        if "\x1e" in text:
            return [p for p in text.split("\x1e") if p]
        return [text]
    packets: list[str] = []
    i = 0
    n = len(data)
    while i < n:
        if data[i] != 0:
            rest = data[i:].decode("utf-8", "replace")
            if rest:
                packets.append(rest)
            break
        i += 1
        length = 0
        while i < n and data[i] != 0xFF:
            length = length * 10 + data[i]
            i += 1
        if i < n and data[i] == 0xFF:
            i += 1
        chunk = data[i : i + length]
        i += length
        packets.append(chunk.decode("utf-8", "replace"))
    return packets


def encode_payload(packet: str) -> bytes:
    body = packet.encode("utf-8")
    digits = [int(ch) for ch in str(len(body))]
    return b"\x00" + bytes(digits) + b"\xff" + body


def parse_open(packet: str) -> dict[str, Any] | None:
    if not packet.startswith("0"):
        return None
    return json.loads(packet[1:])


_EVENT_RE = re.compile(r'^42(\[.*\])$', re.DOTALL)


def parse_event(packet: str) -> tuple[str, Any] | None:
    m = _EVENT_RE.match(packet.strip())
    if not m:
        return None
    arr = json.loads(m.group(1))
    if not arr:
        return None
    name = arr[0]
    payload = arr[1] if len(arr) > 1 else None
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            pass
    return name, payload


def encode_event(name: str, data: Any) -> str:
    if not isinstance(data, str):
        data = json.dumps(data, separators=(",", ":"))
    return "42" + json.dumps([name, data], separators=(",", ":"))


def split_ws_packets(message: str) -> list[str]:
    """One Engine.IO packet per WS frame; v4 may join with 0x1e."""
    if not message:
        return []
    if "\x1e" in message:
        return [p for p in message.split("\x1e") if p]
    return [message]


def classify_eio(packet: str) -> tuple[str, Any]:
    """Classify a single Engine.IO v3 packet (WS: one packet per message)."""
    p = packet if packet is not None else ""
    if p == "2" or p == "2probe":
        return "ping", p
    if p == "3" or p == "3probe":
        return "pong", p
    if p == "5":
        return "upgrade", p
    if p == "6":
        return "noop", p
    if p.startswith("1"):
        return "close", p
    opened = parse_open(p)
    if opened is not None:
        return "open", opened
    ev = parse_event(p)
    if ev is not None:
        return "event", ev
    return "unknown", p
