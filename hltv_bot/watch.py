"""Watch card state, scorebot feed merge, and HTML render.

Telegram send/edit stays in bot.py. This module does not import the bot.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from hltv_bot.debuglog import event_brief
from hltv_bot.format import (
    format_connecting_html,
    format_rich_watch_card,
    format_watch_debug_html,
)
from hltv_bot.live import (
    mark_new_round,
    mark_round_over,
    merge_log,
    merge_scoreboard,
    patch_board_from_log,
    snapshot_from_scoreboard,
)
from hltv_bot.snapshot import snapshot_fingerprint

MIN_EDIT_INTERVAL = 3.0
MIN_EDIT_INTERVAL_WS = 3.0
MAX_EDITS_PER_MINUTE = 19
EDIT_429_FREEZE_CAP = 60.0
WATCH_STALE = 60.0
ADMIN_WS_FAIL_MIN = 2
ADMIN_WS_FAIL_EVERY = 300.0

LOG_EVENT_NAMES = frozenset({"log", "fullLog"})
WATCH_EVENT_NAMES = frozenset(
    {"trace", "ws_fail", "status", "scoreboard", "log", "fullLog", "tick"}
)


@dataclass
class WatchCard:
    chat_id: int
    message_id: int | None = None
    sent_html: str = ""
    edit_timestamps: list[float] = field(default_factory=list)

    def can_edit(self, now: float) -> bool:
        cutoff = now - 60.0
        self.edit_timestamps = [t for t in self.edit_timestamps if t > cutoff]
        if len(self.edit_timestamps) >= MAX_EDITS_PER_MINUTE:
            return False
        if self.edit_timestamps and (now - self.edit_timestamps[-1]) < MIN_EDIT_INTERVAL:
            return False
        return True

    def record_edit(self, now: float) -> None:
        cutoff = now - 60.0
        self.edit_timestamps = [t for t in self.edit_timestamps if t > cutoff]
        self.edit_timestamps.append(now)


@dataclass
class WatchState:
    list_id: str
    meta: dict
    cards: dict[int, WatchCard] = field(default_factory=dict)
    text: str = ""
    fingerprint: str = ""
    stop: threading.Event = field(default_factory=threading.Event)
    last_bump: float = 0.0
    last_edit: float = 0.0
    last_snap: dict = field(default_factory=dict)
    link: str = "connecting"
    pending: bool = False
    notice: str = ""
    next_at: float = 0.0
    trace: list[str] = field(default_factory=list)
    last_data_at: float = 0.0
    debug_view: bool = True
    transport: str = ""
    edit_frozen_until: float = 0.0

    def edits_frozen(self, now: float) -> bool:
        return now < float(self.edit_frozen_until or 0)

    def freeze_edits(self, now: float, retry_after: float) -> float:
        wait = min(max(float(retry_after or 1.0), 1.0), EDIT_429_FREEZE_CAP)
        self.edit_frozen_until = now + wait
        self.pending = True
        return wait

    def card(self, chat_id: int) -> WatchCard:
        c = self.cards.get(int(chat_id))
        if c is None:
            c = WatchCard(chat_id=int(chat_id))
            self.cards[int(chat_id)] = c
        return c


@dataclass
class ScorebotFeed:
    """In-memory scoreboard + kill log for one watch session."""

    board: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    round_seen: int | None = None
    prev_ct: int | None = None
    prev_t: int | None = None
    last_board_brief: str = ""

    def apply_scoreboard(self, payload: dict) -> bool:
        self.board = merge_scoreboard(self.board, payload)
        self.log, self.round_seen = mark_new_round(self.log, self.board, self.round_seen)
        self.log, self.prev_ct, self.prev_t = mark_round_over(
            self.log, self.board, self.prev_ct, self.prev_t
        )
        brief = event_brief("scoreboard", payload)
        changed = brief != self.last_board_brief
        if changed:
            self.last_board_brief = brief
        return changed

    def apply_log(self, payload: Any) -> bool:
        before = self.log
        new_feed = merge_log(self.log, payload)
        if new_feed is before:
            return False
        self.board = patch_board_from_log(self.board, payload)
        self.log = new_feed
        return True


@dataclass
class WsFailDigest:
    """Batch consecutive WS upgrade failures so Telegram is not spammed."""

    min_fails: int = ADMIN_WS_FAIL_MIN
    every: float = ADMIN_WS_FAIL_EVERY
    n: int = 0
    pending: int = 0
    last_err: str = ""
    started: float = 0.0
    last_sent: float = 0.0

    def reset(self) -> None:
        self.n = 0
        self.pending = 0
        self.last_err = ""
        self.started = 0.0
        self.last_sent = 0.0

    def note(self, err: str, now: float) -> bool:
        self.n += 1
        self.pending += 1
        self.last_err = str(err or "")[:160]
        if self.started <= 0:
            self.started = now
        if self.n < self.min_fails:
            return False
        if self.last_sent <= 0:
            return True
        return (now - self.last_sent) >= self.every

    def consume(self, now: float) -> dict:
        out = {
            "n": self.pending,
            "total": self.n,
            "error": self.last_err,
            "elapsed": max(0.0, now - self.started) if self.started else 0.0,
        }
        self.pending = 0
        self.last_sent = now
        return out


def fmt_span(seconds: float) -> str:
    s = max(0.0, float(seconds or 0))
    if s < 90:
        return f"{s:.0f}s"
    return f"{s / 60:.1f}m"


def watch_edit_interval(state: WatchState) -> float:
    """Minimum seconds between watch card edits. Force events do not bypass this."""
    if (state.transport or "") == "ws":
        return MIN_EDIT_INTERVAL_WS
    return MIN_EDIT_INTERVAL


def watch_debug_mode(
    link: str,
    *,
    has_board: bool,
    last_data_at: float,
    now: float,
    stale: float = WATCH_STALE,
) -> bool:
    """DEBUG only when the session is dead or the board is missing/stale.

    Transient handshake / reconnect retry must not replace a live scoreboard.
    """
    if str(link or "") == "disconnected":
        return True
    if not has_board or last_data_at <= 0:
        return True
    if (now - last_data_at) >= stale:
        return True
    return False


def apply_link_status(state: WatchState, payload: dict) -> None:
    new_link = str(payload.get("state") or state.link)
    detail = str(payload.get("detail") or "").strip()
    wait = payload.get("wait")
    state.link = new_link
    if payload.get("transport"):
        state.transport = str(payload.get("transport") or "")
    if new_link in ("connected", "idle") and not detail:
        state.notice = ""
        state.next_at = 0.0
    else:
        state.notice = detail or {
            "connecting": "connecting",
            "reconnect": "reconnect",
            "disconnected": "disconnected",
        }.get(new_link, new_link)
        if wait not in (None, ""):
            try:
                state.next_at = time.time() + float(wait)
            except (TypeError, ValueError):
                pass


def watch_fingerprint(
    snap: dict,
    *,
    debug: bool,
    link: str,
    notice: str,
    next_at: float,
    trace_tail: str = "",
) -> str:
    extra = "|" + link + "|" + notice + "|" + str(int(next_at or 0))
    if debug:
        return "debug|" + trace_tail + extra
    return snapshot_fingerprint(snap) + extra


def render_watch(
    state: WatchState,
    board: dict | None,
    feed: list,
    *,
    debug: bool | None = None,
    live: bool | None = None,
    now: float | None = None,
) -> tuple[str, dict, bool]:
    """Return (html, snap, debug). One Rich card: score + history + roster + log."""
    now = time.time() if now is None else now
    if debug is None:
        debug = watch_debug_mode(
            state.link,
            has_board=bool(board),
            last_data_at=state.last_data_at,
            now=now,
        )
    if debug:
        html = format_watch_debug_html(
            team1=str(state.meta.get("team1") or "?"),
            team2=str(state.meta.get("team2") or "?"),
            list_id=state.list_id,
            url=state.meta.get("url"),
            link=state.link,
            notice=state.notice,
            next_at=state.next_at,
            lines=list(state.trace),
        )
        snap = {
            "live": True,
            "url": state.meta.get("url"),
            "team1": {"name": state.meta.get("team1")},
            "team2": {"name": state.meta.get("team2")},
            "log": feed,
            "teams": [],
            "link": state.link,
            "notice": state.notice,
            "next_at": state.next_at,
            "transport": state.transport,
        }
        return html, snap, True
    if board:
        snap = snapshot_from_scoreboard(board, meta=state.meta, log=feed)
        snap["link"] = state.link
        snap["notice"] = state.notice
        snap["next_at"] = state.next_at
        snap["transport"] = state.transport
        if live is not None:
            snap["live"] = live
        return format_rich_watch_card(snap), snap, False
    snap = {
        "live": True,
        "url": state.meta.get("url"),
        "team1": {"name": state.meta.get("team1")},
        "team2": {"name": state.meta.get("team2")},
        "log": feed,
        "teams": [],
        "link": state.link,
        "notice": state.notice,
        "next_at": state.next_at,
        "transport": state.transport,
    }
    html = format_connecting_html(
        team1=str(state.meta.get("team1") or "?"),
        team2=str(state.meta.get("team2") or "?"),
        list_id=state.list_id,
        url=state.meta.get("url"),
        link=state.link,
        notice=state.notice,
        next_at=state.next_at,
    )
    return html, snap, False
