"""Engine.IO v3 xhr-polling encode/decode (as used by scorebot-lb)."""

from __future__ import annotations

import json
import re
from typing import Any


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
