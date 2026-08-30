"""Short, token-safe summaries for CLI debug logs."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

CST = timezone(timedelta(hours=8))
TRACE_MAX = 24


def clip(text: object, n: int = 400) -> str:
    s = str(text).replace("\n", " ")
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def board_brief(board: dict[str, Any] | None) -> str:
    if not isinstance(board, dict) or not board:
        return "empty"
    keys = ",".join(list(board.keys())[:16])
    return (
        f"ct={board.get('ctScore', board.get('counterTerroristScore'))}"
        f" t={board.get('tScore', board.get('terroristScore'))}"
        f" r={board.get('currentRound', board.get('round'))}"
        f" map={board.get('mapName', board.get('map'))}"
        f" keys={keys}"
    )


def log_brief(payload: Any) -> str:
    block = payload
    if isinstance(payload, dict) and "log" in payload:
        block = payload["log"]
    if isinstance(block, dict):
        block = [block]
    if not isinstance(block, list):
        return clip(payload, 200)
    kinds = []
    for it in block[:8]:
        if isinstance(it, dict) and it:
            kinds.append(next(iter(it.keys())))
        else:
            kinds.append(type(it).__name__)
    extra = f"+{len(block) - 8}" if len(block) > 8 else ""
    return f"n={len(block)} {','.join(kinds)}{extra}"


def event_brief(name: str, payload: Any) -> str:
    if name == "scoreboard" and isinstance(payload, dict):
        return board_brief(payload)
    if name == "log":
        return log_brief(payload)
    if name == "status" and isinstance(payload, dict):
        return f"state={payload.get('state')} {clip(payload.get('detail') or '', 80)}"
    if name == "tick":
        return "tick"
    return clip(payload, 240)


def append_trace(lines: list[str], text: object) -> bool:
    """Append a clocked line. Skip empties and consecutive duplicates. Return True if added."""
    body = clip(text, 160).strip()
    if not body:
        return False
    if lines:
        prev = lines[-1]
        if prev.split(" ", 1)[-1] == body:
            return False
    clock = datetime.now(CST).strftime("%H:%M:%S")
    lines.append(f"{clock} {body}")
    extra = len(lines) - TRACE_MAX
    if extra > 0:
        del lines[:extra]
    return True


def snap_brief(snap: dict[str, Any] | None) -> str:
    if not isinstance(snap, dict) or not snap:
        return "empty"
    teams = snap.get("teams") or []
    n1 = len((teams[0] or {}).get("players") or []) if teams else 0
    n2 = len((teams[1] or {}).get("players") or []) if len(teams) > 1 else 0
    log = snap.get("log") or []
    return (
        f"score={snap.get('scoreText')} round={snap.get('roundText')}"
        f" link={snap.get('link')} players={n1}/{n2} log={len(log)}"
        f" url={bool(snap.get('url'))}"
    )
