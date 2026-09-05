from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("hltv_bot")

from hltv_bot.chats import add_group, group_ids, list_groups, remove_group
from hltv_bot.debuglog import append_trace, clip, event_brief, snap_brief
from hltv_bot.format import (
    format_connecting_html,
    format_kv_table,
    format_match_list,
    format_rich_html,
    format_watch_debug_html,
    h,
    plain_to_rich,
)
from hltv_bot.http import CloudflareError
from hltv_bot.live import (
    mark_new_round,
    mark_round_over,
    merge_log,
    patch_board_from_log,
    snapshot_from_scoreboard,
)
from hltv_bot.matches import fetch_match_meta, fetch_matches
from hltv_bot.scorebot import WS_RETRY_EVERY, iter_scorebot, scorebot_base
from hltv_bot.ratelimit import Cooldown
from hltv_bot.session import BrowserSession, load_session, save_cookie
from hltv_bot.snapshot import snapshot_fingerprint
from hltv_bot.telegram_api import Telegram, is_not_modified

DEFAULT_ADMIN_ID = 1442477170

HELP = """\
<h3>hltv-bot</h3>
<ul>
<li><code>/matches</code> — 今日比赛</li>
<li><code>/watch</code> — 本群观赛（已有场次发 /watch 加入）</li>
<li><code>/bump</code> — 顶到最新</li>
<li><code>/stop</code> — 本群退出（/stop all 停全部）</li>
</ul>
<h4>管理员</h4>
<ul>
<li><code>/allow</code> — 授权本群</li>
<li><code>/deny</code> — 取消授权</li>
<li><code>/groups</code> — 已授权群</li>
<li><code>/cookie</code> — 更新 Cookie</li>
<li><code>/status</code> — 状态</li>
<li><code>/debug</code> — 调试（user/chat/admin）</li>
</ul>
"""

ADMIN_CMDS = frozenset(
    {
        "/allow",
        "/deny",
        "/groups",
        "/cookie",
        "/updatecookie",
        "/update_cookie",
        "/status",
        "/debug",
    }
)

CMD_COOLDOWN = {
    "/matches": 8.0,
    "/matchs": 8.0,
    "/match": 8.0,
    "/watch": 6.0,
    "/bump": 4.0,
    "/new": 4.0,
    "/cookie": 3.0,
}
DEFAULT_CMD_COOLDOWN = 1.2
MIN_EDIT_INTERVAL = 1.8
WATCH_STALE = 60.0
MSG_TTL = 30.0
GET_UPDATES_FAIL_SLEEP = 3.0
TG_COMMANDS_GAP = 0.4
# WS retries every 30s on poll; ping admin after 2 fails, then batch every 5m.
ADMIN_WS_FAIL_MIN = 2
ADMIN_WS_FAIL_EVERY = 300.0
_KEEP_USER_CMDS = frozenset({"/watch"})

USER_BOT_COMMANDS = [
    {"command": "matches", "description": "今日比赛"},
    {"command": "watch", "description": "本群观赛(已有场次 /watch 加入)"},
    {"command": "bump", "description": "顶到最新"},
    {"command": "stop", "description": "本群退出(/stop all 停全部)"},
    {"command": "help", "description": "帮助"},
]
ADMIN_BOT_COMMANDS = USER_BOT_COMMANDS + [
    {"command": "allow", "description": "授权本群"},
    {"command": "deny", "description": "取消授权"},
    {"command": "groups", "description": "已授权群"},
    {"command": "cookie", "description": "更新 Cookie"},
    {"command": "status", "description": "状态"},
    {"command": "debug", "description": "调试"},
]


@dataclass
class WatchCard:
    chat_id: int
    message_id: int | None = None
    sent_html: str = ""


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

    def card(self, chat_id: int) -> WatchCard:
        c = self.cards.get(int(chat_id))
        if c is None:
            c = WatchCard(chat_id=int(chat_id))
            self.cards[int(chat_id)] = c
        return c


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


def _fmt_span(seconds: float) -> str:
    s = max(0.0, float(seconds or 0))
    if s < 90:
        return f"{s:.0f}s"
    return f"{s / 60:.1f}m"


def watch_debug_mode(
    link: str,
    *,
    has_board: bool,
    last_data_at: float,
    now: float,
    stale: float = WATCH_STALE,
) -> bool:
    """DEBUG only when the session is dead or the board is missing/stale.

    Transient poll 5xx / handshake retry must not replace a live scoreboard.
    """
    if str(link or "") == "disconnected":
        return True
    if not has_board or last_data_at <= 0:
        return True
    if (now - last_data_at) >= stale:
        return True
    return False


class HltvTelegramBot:
    def __init__(
        self,
        tg: Telegram,
        session: BrowserSession,
        *,
        admin_ids: set[int] | None = None,
        bump_seconds: float = 0.0,
    ):
        self.tg = tg
        self.session = session
        self.admin_ids = admin_ids or {DEFAULT_ADMIN_ID}
        self.bump_seconds = bump_seconds
        self.watch: WatchState | None = None
        self._thread: threading.Thread | None = None
        self._await_cookie: set[int] = set()
        self._cool = Cooldown()
        self._ws_fail = WsFailDigest()
        self.msg_ttl = MSG_TTL

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and int(user_id) in self.admin_ids

    def can_setup_chat(self, chat_id: int, user_id: int | None, chat_type: str) -> bool:
        """/allow /deny in a group that is not yet on the list."""
        if self.is_admin(user_id):
            return True
        if chat_type not in ("group", "supergroup"):
            return False
        if user_id:
            st = self.tg.chat_member_status(chat_id, int(user_id))
            if st in ("creator", "administrator"):
                return True
        admins = self.tg.chat_admin_user_ids(chat_id)
        return bool(admins & self.admin_ids)

    def chat_allowed(self, chat_id: int, *, user_id: int | None = None) -> bool:
        if self.is_admin(user_id):
            return True
        return int(chat_id) in group_ids()

    def handle_text(
        self,
        chat_id: int,
        text: str,
        *,
        message_id: int | None = None,
        user_id: int | None = None,
        chat_title: str = "",
        chat_type: str = "",
    ) -> None:
        parts = text.strip().split()
        cmd = (parts[0].split("@")[0] if parts else "").lower()
        arg = " ".join(parts[1:]) if len(parts) > 1 else ""
        listed = int(chat_id) in group_ids()
        log.info(
            "msg chat=%s type=%s user=%s cmd=%s listed=%s bot_admin=%s text=%r",
            chat_id,
            chat_type,
            user_id,
            cmd,
            listed,
            self.is_admin(user_id),
            (text or "")[:120],
        )
        if chat_id in self._await_cookie and not cmd.startswith("/"):
            if not self.is_admin(user_id):
                return
            self._apply_cookie(chat_id, text, message_id=message_id)
            return
        if cmd in {"/allow", "/deny"}:
            if not self.can_setup_chat(chat_id, user_id, chat_type):
                log.info("deny setup cmd %s user=%s chat=%s", cmd, user_id, chat_id)
                self._reply(
                    chat_id,
                    f"无权限授权本群\n你的 id: <code>{user_id}</code>\nchat: <code>{chat_id}</code>",
                )
                return
        elif cmd in ADMIN_CMDS and not self.is_admin(user_id):
            log.info("deny admin cmd %s user=%s chat=%s", cmd, user_id, chat_id)
            if cmd in {"/debug", "/status", "/groups", "/cookie"}:
                self._reply(
                    chat_id,
                    f"无权限\n你的 id: <code>{user_id}</code>",
                )
            return
        if cmd not in ADMIN_CMDS | {"/start", "/help"} and not listed and not self.is_admin(user_id):
            log.info("skip cmd=%s chat=%s not in allow-list", cmd, chat_id)
            return
        if (
            cmd.startswith("/")
            and cmd not in _KEEP_USER_CMDS
            and message_id is not None
        ):
            self._schedule_delete(chat_id, int(message_id))
        if cmd.startswith("/") and user_id is not None:
            interval = CMD_COOLDOWN.get(cmd, DEFAULT_CMD_COOLDOWN)
            key = f"{user_id}:{cmd}"
            if not self._cool.allow(key, interval):
                wait = self._cool.remaining(key, interval)
                if cmd in {"/matches", "/matchs", "/match", "/watch", "/bump"}:
                    self._reply(chat_id, f"稍等 {wait:.0f}s")
                return
        if cmd in ("/start", "/help"):
            self._await_cookie.discard(chat_id)
            if self.is_admin(user_id) or self.chat_allowed(chat_id, user_id=user_id):
                self._reply(chat_id, HELP)
        elif cmd == "/allow":
            self._cmd_allow(chat_id, arg, chat_title=chat_title, chat_type=chat_type)
        elif cmd == "/deny":
            self._cmd_deny(chat_id, arg)
        elif cmd == "/groups":
            self._cmd_groups(chat_id)
        elif cmd in ("/matches", "/matchs", "/match"):
            self._await_cookie.discard(chat_id)
            self._cmd_matches(chat_id, arg)
        elif cmd == "/watch":
            self._await_cookie.discard(chat_id)
            self._cmd_watch(chat_id, arg)
        elif cmd in ("/bump", "/new"):
            self._await_cookie.discard(chat_id)
            self._cmd_bump(chat_id)
        elif cmd == "/stop":
            self._await_cookie.discard(chat_id)
            self._cmd_stop(chat_id, arg)
        elif cmd == "/status":
            self._await_cookie.discard(chat_id)
            self._cmd_status(chat_id)
        elif cmd in ("/cookie", "/updatecookie", "/update_cookie"):
            self._cmd_cookie(chat_id, arg, message_id=message_id)
        elif cmd == "/debug":
            self._cmd_debug(chat_id, user_id=user_id, chat_title=chat_title, chat_type=chat_type)

    def _cmd_matches(self, chat_id: int, arg: str = "") -> None:
        all_mode = arg.strip().lower() in {"all", "全部", "*", "full"}
        try:
            rows = fetch_matches(self.session)
        except CloudflareError as e:
            self._reply(chat_id, f"Cloudflare 拦了列表页：{e}\n发 /cookie 更新 Cookie")
            return
        if not rows:
            self._reply(chat_id, "列表是空的（或解析失败）")
            return
        text = format_match_list(rows, starred_only=not all_mode)
        log.debug("matches text_len=%s", len(text))
        self._reply(chat_id, text)

    def _watch_hint(self, list_id: str) -> str:
        return (
            f"本群已加入。其它群发 <code>/watch</code> 或 "
            f"<code>/watch {h(list_id)}</code> 加入同一场。\n"
            "本群退出 <code>/stop</code> · 全部停止 <code>/stop all</code>"
        )

    def _join_watch(self, state: WatchState, chat_id: int) -> None:
        html = state.text or self._watch_card_html(state, board=None, feed=[])
        card = state.cards.get(int(chat_id))
        if card and card.message_id:
            self._reply(
                chat_id,
                "本群已在观赛。/bump 顶到最新 · /stop 退出本群",
            )
            return
        log.info("watch join chat=%s listId=%s", chat_id, state.list_id)
        self._flush_watch(state, html, send_new=True, chat_id=chat_id)
        self._reply(chat_id, self._watch_hint(state.list_id))

    def _put_watch_card(self, state: WatchState, chat_id: int, html: str) -> None:
        card = state.card(chat_id)
        try:
            if card.message_id:
                self._flush_watch(state, html, chat_id=chat_id)
            else:
                self._flush_watch(state, html, send_new=True, chat_id=chat_id)
        except Exception:
            log.exception("watch card failed chat=%s", chat_id)

    def _cmd_watch(self, chat_id: int, arg: str) -> None:
        raw = arg.strip()
        w = self.watch
        live = w is not None and not w.stop.is_set()
        if not raw:
            if live and w is not None:
                self._join_watch(w, chat_id)
                return
            self._reply(
                chat_id,
                "用法: /watch 2396932\n已有观赛时本群发 /watch 即可加入",
            )
            return
        try:
            meta = fetch_match_meta(self.session, raw)
        except CloudflareError as e:
            self._reply(chat_id, f"详情页 Cloudflare：{e}\n发 /cookie 更新 Cookie")
            return
        list_id = meta.get("scorebotId") or "".join(ch for ch in raw if ch.isdigit())
        if not list_id:
            self._reply(chat_id, "没有 data-scorebot-id")
            return
        list_id = str(list_id)
        if live and w is not None and w.list_id == list_id:
            self._join_watch(w, chat_id)
            return
        old_cards: dict[int, WatchCard] = {}
        if live and w is not None:
            old_cards = dict(w.cards)
        self._stop_watch()
        t1, t2 = meta.get("team1") or "?", meta.get("team2") or "?"
        log.info("watch start listId=%s %s vs %s url=%s", list_id, t1, t2, meta.get("url"))
        self._ws_fail.reset()
        state = WatchState(
            list_id=list_id,
            meta=meta,
            cards=old_cards,
            last_bump=time.time(),
            debug_view=True,
        )
        append_trace(state.trace, f"watch start listId={list_id} {t1} vs {t2}")
        html = self._watch_card_html(state, board=None, feed=[])
        targets = {int(chat_id)}
        targets.update(old_cards)
        for cid in sorted(targets):
            self._put_watch_card(state, cid, html)
        self.watch = state
        self._thread = threading.Thread(target=self._watch_loop, args=(state,), daemon=True)
        self._thread.start()
        self._reply(chat_id, self._watch_hint(list_id))

    def _cmd_bump(self, chat_id: int) -> None:
        w = self.watch
        if not w or w.stop.is_set() or not w.text:
            self._reply(chat_id, "没有正在 watch 的消息")
            return
        card = w.cards.get(int(chat_id))
        log.info(
            "bump chat=%s old_msg=%s",
            chat_id,
            card.message_id if card else None,
        )
        self._flush_watch(w, w.text, send_new=True, chat_id=chat_id)

    def _cmd_stop(self, chat_id: int, arg: str = "") -> None:
        w = self.watch
        if not w or w.stop.is_set():
            self._reply(chat_id, "没有正在 watch")
            return
        if arg.strip().lower() in {"all", "全部", "*"}:
            n = len(w.cards)
            self._stop_watch(delete_cards=True)
            self._reply(chat_id, f"已停止全部（{n} 个群）")
            return
        self._delete_watch_cards(w, chat_id=int(chat_id))
        w.cards.pop(int(chat_id), None)
        if not w.cards:
            self._stop_watch()
            self._reply(chat_id, "已停止")
            return
        log.info("watch leave chat=%s remaining=%s", chat_id, list(w.cards))
        self._reply(
            chat_id,
            "本群已退出。其它群仍在观赛。全部停止发 /stop all",
        )

    def _cmd_status(self, chat_id: int) -> None:
        names = self.session.cookie_names()
        w = self.watch
        watch_line = "idle"
        if w and not w.stop.is_set():
            cards = ",".join(
                f"{c.chat_id}:{c.message_id}" for c in w.cards.values()
            ) or "-"
            watch_line = f"watching {w.list_id} cards={cards}"
        self._reply(
            chat_id,
            format_kv_table(
                "Status",
                [
                    ("impersonate", h(self.session.impersonate)),
                    ("cf_clearance", "yes" if self.session.has_clearance() else "NO"),
                    ("cookies", h(", ".join(names) or "(none)")),
                    ("session", h(str(self.session.path or ""))),
                    ("watch", h(watch_line)),
                    ("new card", "/bump only"),
                    ("admins", h(", ".join(str(i) for i in sorted(self.admin_ids)))),
                    ("groups", str(len(list_groups()))),
                ],
            ),
        )

    def _cmd_allow(self, chat_id: int, arg: str, *, chat_title: str, chat_type: str) -> None:
        target = arg.strip()
        title = chat_title
        if target.lstrip("-").isdigit():
            gid = int(target)
            title = title if gid == chat_id else ""
        elif chat_type in ("group", "supergroup"):
            gid = int(chat_id)
        else:
            self._reply(chat_id, "在目标群里发 /allow，或 /allow -100xxxxxxxxxx")
            return
        added = add_group(gid, title)
        log.info("allow chat=%s title=%s added=%s", gid, title, added)
        self._reply(
            chat_id,
            ("已加入" if added else "已在名单里") + f" <code>{gid}</code> {title}".rstrip(),
        )

    def _cmd_deny(self, chat_id: int, arg: str) -> None:
        target = arg.strip()
        if target.lstrip("-").isdigit():
            gid = int(target)
        else:
            gid = int(chat_id)
        if remove_group(gid):
            self._reply(chat_id, f"已移除 <code>{gid}</code>")
        else:
            self._reply(chat_id, f"名单里没有 <code>{gid}</code>")

    def _cmd_debug(
        self,
        chat_id: int,
        *,
        user_id: int | None,
        chat_title: str,
        chat_type: str,
    ) -> None:
        rows = list_groups()
        listed = int(chat_id) in group_ids()
        group_html = (
            "<br>".join(
                f"<code>{h(g.get('id'))}</code> {h(g.get('title') or '')}" for g in rows
            )
            if rows
            else "<i>empty</i>"
        )
        html = format_kv_table(
            "debug",
            [
                ("user_id", f"<code>{h(user_id)}</code>"),
                ("chat_id", f"<code>{h(chat_id)}</code>"),
                ("chat_type", h(chat_type or "?")),
                ("title", h(chat_title or "-")),
                ("bot_admin", str(self.is_admin(user_id))),
                ("can_setup", str(self.can_setup_chat(chat_id, user_id, chat_type))),
                ("chat_listed", str(listed)),
                ("admins", h(", ".join(str(i) for i in sorted(self.admin_ids)))),
                ("groups", group_html),
            ],
        )
        log.info(
            "debug user=%s chat=%s type=%s listed=%s admin=%s groups=%s",
            user_id,
            chat_id,
            chat_type,
            listed,
            self.is_admin(user_id),
            len(rows),
        )
        self._reply(chat_id, html)

    def _cmd_groups(self, chat_id: int) -> None:
        rows = list_groups()
        if not rows:
            self._reply(chat_id, "还没有授权群。把 bot 拉进群后发 /allow")
            return
        body = "".join(
            f"<tr><td><code>{h(g.get('id'))}</code></td><td>{h(g.get('title') or '')}</td></tr>"
            for g in rows
        )
        self._reply(
            chat_id,
            f"<h3>授权群</h3><table bordered striped compact>{body}</table>",
        )

    def handle_added_to_chat(self, upd: dict) -> None:
        member = upd.get("my_chat_member") or {}
        chat = member.get("chat") or {}
        new = (member.get("new_chat_member") or {}).get("status") or ""
        old = (member.get("old_chat_member") or {}).get("status") or ""
        from_id = (member.get("from") or {}).get("id")
        cid = chat.get("id")
        title = chat.get("title") or ""
        ctype = chat.get("type") or ""
        log.info(
            "my_chat_member chat=%s type=%s title=%r from=%s %s -> %s",
            cid,
            ctype,
            title,
            from_id,
            old,
            new,
        )
        if new not in ("member", "administrator") or old in ("member", "administrator"):
            return
        if cid is None:
            return
        if self.can_setup_chat(int(cid), from_id, ctype):
            self._reply(
                cid,
                f"<h3>已进群</h3><p><b>{h(title)}</b></p><p>发 /allow 加入推送名单</p>",
            )
            return
        log.info("added to chat but adder cannot /allow from=%s", from_id)

    def _session_path(self) -> Path:
        return Path(self.session.path or "data/session.json")

    def _cmd_cookie(self, chat_id: int, arg: str, *, message_id: int | None) -> None:
        if arg.strip():
            self._apply_cookie(chat_id, arg, message_id=message_id)
            return
        self._await_cookie.add(chat_id)
        self._reply(
            chat_id,
            "把 DevTools → Network → Cookie 整行贴过来（可带 Cookie: 前缀），\n"
            "或直接贴整份 data/session.json。\n"
            "发完后会尽量删掉你的消息。取消请发 /status。",
        )

    def _apply_cookie(self, chat_id: int, raw: str, *, message_id: int | None) -> None:
        self._await_cookie.discard(chat_id)
        path = self._session_path()
        save_cookie(path, raw)
        self.session = load_session(path)
        names = self.session.cookie_names()
        if not names:
            self._reply(chat_id, "Cookie 是空的，没写入有效内容")
            return
        if message_id is not None:
            self.tg.delete_message(chat_id, message_id)
        extra = ""
        if self.watch and not self.watch.stop.is_set():
            extra = "\n正在 watch：新 cookie 下一轮请求会用上；仍 403 就 /stop 再 /watch。"
        self._reply(
            chat_id,
            "Cookie 已更新\n"
            f"cf_clearance: {'yes' if self.session.has_clearance() else 'NO（请贴完整头）'}\n"
            f"names: {', '.join(names)}"
            + extra,
        )

    def _delete_watch_cards(self, state: WatchState, *, chat_id: int | None = None) -> None:
        cards = (
            [state.cards[int(chat_id)]]
            if chat_id is not None and int(chat_id) in state.cards
            else list(state.cards.values())
        )
        for card in cards:
            if not card.message_id:
                continue
            try:
                self.tg.delete_message(card.chat_id, card.message_id)
                log.info("watch delete chat=%s msg=%s", card.chat_id, card.message_id)
            except Exception:
                log.debug(
                    "watch delete failed chat=%s msg=%s",
                    card.chat_id,
                    card.message_id,
                )
            card.message_id = None

    def _stop_watch(self, *, delete_cards: bool = False) -> None:
        if self.watch:
            if delete_cards:
                self._delete_watch_cards(self.watch)
            self.watch.stop.set()
        self.watch = None
        self._ws_fail.reset()

    def _watch_loop(self, state: WatchState) -> None:
        board: dict = {}
        feed: list = []
        round_seen: int | None = None
        prev_ct: int | None = None
        prev_t: int | None = None
        try:
            stream = iter_scorebot(
                self.session,
                state.list_id,
                base=scorebot_base(state.meta.get("scorebotUrl")),
            )
            for name, payload in stream:
                if state.stop.is_set() or self.watch is not state:
                    log.info("watch stop listId=%s event=%s", state.list_id, name)
                    return
                log.debug("watch event %s %s", name, event_brief(name, payload))
                status_changed = False
                if name == "trace" and isinstance(payload, dict):
                    append_trace(state.trace, payload.get("text") or "")
                elif name == "ws_fail" and isinstance(payload, dict):
                    self._on_ws_fail(state, payload)
                    continue
                elif name == "status" and isinstance(payload, dict):
                    new_link = str(payload.get("state") or state.link)
                    detail = str(payload.get("detail") or "").strip()
                    wait = payload.get("wait")
                    state.link = new_link
                    if payload.get("transport"):
                        state.transport = str(payload.get("transport") or "")
                        if state.transport == "ws":
                            self._ws_fail.reset()
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
                    status_changed = True
                    append_trace(state.trace, f"link {new_link} {state.notice}".strip())
                    log.info(
                        "watch link %s notice=%s next_at=%.0f",
                        new_link,
                        state.notice,
                        state.next_at,
                    )
                elif name == "scoreboard" and isinstance(payload, dict):
                    board = payload
                    feed, round_seen = mark_new_round(feed, board, round_seen)
                    feed, prev_ct, prev_t = mark_round_over(feed, board, prev_ct, prev_t)
                    state.last_data_at = time.time()
                    log.info("watch scoreboard %s", event_brief(name, payload))
                elif name == "log":
                    before = len(feed)
                    new_feed = merge_log(feed, payload)
                    if new_feed is not feed:
                        board = patch_board_from_log(board, payload)
                    feed = new_feed
                    state.last_data_at = time.time()
                    log.info("watch log %s feed %s -> %s", event_brief(name, payload), before, len(feed))
                elif name == "tick":
                    now = time.time()
                    if (
                        board
                        and state.last_data_at
                        and (now - state.last_data_at) >= WATCH_STALE
                        and not state.debug_view
                    ):
                        append_trace(
                            state.trace,
                            f"stale no scoreboard/log {int(now - state.last_data_at)}s",
                        )
                        status_changed = True
                    elif state.pending and state.text:
                        self._flush_watch(state, state.text)
                        continue
                    else:
                        continue
                else:
                    log.debug("watch ignore event %s", name)
                    continue
                html, snap, debug = self._watch_render(state, board, feed)
                fp = (
                    ("debug|" + (state.trace[-1] if state.trace else ""))
                    if debug
                    else snapshot_fingerprint(snap)
                ) + "|" + state.link + "|" + state.notice + "|" + str(int(state.next_at or 0))
                mode_switch = debug != state.debug_view
                if fp == state.fingerprint and not status_changed and not mode_switch:
                    log.debug("watch skip unchanged fp=%s", clip(fp, 120))
                    continue
                state.debug_view = debug
                state.text = html
                state.last_snap = snap
                state.fingerprint = fp
                state.pending = True
                now = time.time()
                head_type = ""
                if isinstance(snap, dict):
                    head = (snap.get("log") or [{}])[0]
                    if isinstance(head, dict):
                        head_type = str(head.get("type") or "")
                force = status_changed or mode_switch or head_type in {
                    "round_start",
                    "round_over",
                    "round_over_ct",
                    "round_over_t",
                } or any(
                    s in html
                    for s in (
                        "<mark>3K</mark>",
                        "<mark>4K</mark>",
                        "<mark>ACE</mark>",
                    )
                )
                wait = now - state.last_edit
                if wait < MIN_EDIT_INTERVAL and not force:
                    log.debug(
                        "watch defer interval wait=%.2fs force=%s %s",
                        wait,
                        force,
                        snap_brief(snap),
                    )
                    continue
                log.debug("watch render %s html_len=%s debug=%s %s", name, len(html), debug, snap_brief(snap))
                self._flush_watch(state, html)
                continue
        except CloudflareError as e:
            state.notice = f"Cloudflare {e.status} · /cookie"
            state.next_at = 0.0
            append_trace(state.trace, state.notice)
            self._mark_watch_down(state, "disconnected")
            self._notify_admins(f"⚠️ <b>HLTV Cookie 已失效 (Cloudflare {e.status})</b>\n请在有环境的机器烤好后发 /cookie 更新")
        except Exception as e:
            state.notice = str(e)[:80] or "ended"
            append_trace(state.trace, state.notice)
            self._mark_watch_down(state, "disconnected")
            if not state.stop.is_set():
                log.info("watch ended: %s", e)

    def _notify_admins(self, text: str) -> None:
        """Plain HTML to admin DMs. No auto-delete; not a watch card."""
        for aid in sorted(self.admin_ids):
            try:
                self.tg.send_message(aid, text)
            except Exception:
                log.exception("notify admin %s", aid)

    def _on_ws_fail(self, state: WatchState, payload: dict) -> None:
        err = str(payload.get("error") or "websocket failed")
        now = time.monotonic()
        if not self._ws_fail.note(err, now):
            log.debug("ws fail queued n=%s pending=%s", self._ws_fail.n, self._ws_fail.pending)
            return
        info = self._ws_fail.consume(now)
        t1 = str(state.meta.get("team1") or "?")
        t2 = str(state.meta.get("team2") or "?")
        text = (
            f"<b>scorebot WS 持续失败</b> ×{info['total']} / {_fmt_span(info['elapsed'])}\n"
            f"listId=<code>{h(state.list_id)}</code> {h(t1)} vs {h(t2)}\n"
            f"本批 {info['n']} 次 · 仍走 poll · 每 {int(WS_RETRY_EVERY)}s 再试\n"
            f"last: <code>{h(info['error'])}</code>"
        )
        log.info(
            "ws fail admin n=%s total=%s listId=%s last=%s",
            info["n"],
            info["total"],
            state.list_id,
            clip(info["error"], 80),
        )
        self._notify_admins(text)

    def _schedule_delete(self, chat_id: int, message_id: int) -> None:
        delay = float(self.msg_ttl or 0)
        if delay <= 0 or not message_id:
            return

        def _run() -> None:
            try:
                self.tg.delete_message(chat_id, message_id)
            except Exception:
                log.debug("delete_message chat=%s msg=%s failed", chat_id, message_id)

        t = threading.Timer(delay, _run)
        t.daemon = True
        t.start()

    def _reply(self, chat_id: int, text: str) -> dict:
        msg = self.tg.send_message(chat_id, text)
        mid = msg.get("message_id") if isinstance(msg, dict) else None
        if mid is not None:
            self._schedule_delete(chat_id, int(mid))
        return msg

    def _send_rich(self, chat_id: int, html: str) -> dict:
        try:
            return self.tg.send_rich(chat_id, html)
        except Exception as e:
            log.warning("sendRichMessage failed: %s html=%s", e, clip(html, 240))
            return self.tg.send_rich(chat_id, plain_to_rich(html))

    def _flush_watch(
        self,
        state: WatchState,
        html: str,
        *,
        send_new: bool = False,
        chat_id: int | None = None,
    ) -> None:
        if not html:
            return
        now = time.time()
        snap = state.last_snap or {}
        state.text = html
        if send_new:
            cid = int(chat_id) if chat_id is not None else next(iter(state.cards), 0)
            if not cid:
                log.warning("watch send skipped: no chat")
                return
            msg = self._send_rich(cid, html)
            card = state.card(cid)
            if isinstance(msg, dict) and msg.get("message_id"):
                card.message_id = msg["message_id"]
            card.sent_html = html
            state.last_bump = now
            state.last_edit = now
            state.pending = False
            log.info("watch send chat=%s msg=%s %s", cid, card.message_id, snap_brief(snap))
            return
        targets = [state.card(chat_id)] if chat_id is not None else list(state.cards.values())
        if not targets:
            log.warning("watch edit skipped: no cards (will not send a new card)")
            return
        edited = False
        for card in targets:
            if html == card.sent_html:
                continue
            if not card.message_id:
                log.warning(
                    "watch edit skipped: no message_id chat=%s (will not send a new card)",
                    card.chat_id,
                )
                continue
            try:
                self.tg.edit_rich(card.chat_id, card.message_id, html)
                log.info(
                    "watch edit chat=%s msg=%s %s",
                    card.chat_id,
                    card.message_id,
                    snap_brief(snap),
                )
            except Exception as e:
                if is_not_modified(e):
                    log.debug("watch not modified chat=%s msg=%s", card.chat_id, card.message_id)
                else:
                    log.warning(
                        "watch edit_rich failed chat=%s: %s html=%s",
                        card.chat_id,
                        e,
                        clip(html, 240),
                    )
                    continue
            card.sent_html = html
            edited = True
        state.pending = False
        if edited:
            state.last_edit = now

    def _watch_card_html(
        self,
        state: WatchState,
        *,
        board: dict | None,
        feed: list,
        debug: bool | None = None,
    ) -> str:
        now = time.time()
        if debug is None:
            debug = watch_debug_mode(
                state.link,
                has_board=bool(board),
                last_data_at=state.last_data_at,
                now=now,
            )
        if debug:
            return format_watch_debug_html(
                team1=str(state.meta.get("team1") or "?"),
                team2=str(state.meta.get("team2") or "?"),
                list_id=state.list_id,
                url=state.meta.get("url"),
                link=state.link,
                notice=state.notice,
                next_at=state.next_at,
                lines=list(state.trace),
            )
        if board:
            snap = snapshot_from_scoreboard(board, meta=state.meta, log=feed)
            snap["link"] = state.link
            snap["notice"] = state.notice
            snap["next_at"] = state.next_at
            snap["transport"] = state.transport
            return format_rich_html(snap)
        return format_connecting_html(
            team1=str(state.meta.get("team1") or "?"),
            team2=str(state.meta.get("team2") or "?"),
            list_id=state.list_id,
            url=state.meta.get("url"),
            link=state.link,
            notice=state.notice,
            next_at=state.next_at,
        )

    def _watch_render(
        self, state: WatchState, board: dict, feed: list
    ) -> tuple[str, dict, bool]:
        now = time.time()
        debug = watch_debug_mode(
            state.link,
            has_board=bool(board),
            last_data_at=state.last_data_at,
            now=now,
        )
        if board:
            snap = snapshot_from_scoreboard(board, meta=state.meta, log=feed)
        else:
            snap = {
                "live": True,
                "url": state.meta.get("url"),
                "team1": {"name": state.meta.get("team1")},
                "team2": {"name": state.meta.get("team2")},
                "log": feed,
                "teams": [],
            }
        snap["link"] = state.link
        snap["notice"] = state.notice
        snap["next_at"] = state.next_at
        snap["transport"] = state.transport
        html = self._watch_card_html(state, board=board, feed=feed, debug=debug)
        return html, snap, debug

    def _mark_watch_down(self, state: WatchState, link: str) -> None:
        state.link = link
        state.debug_view = True
        snap = dict(state.last_snap or {"live": True, "teams": [], "log": []})
        snap["link"] = link
        snap["notice"] = state.notice
        snap["next_at"] = state.next_at
        state.last_snap = snap
        try:
            html = self._watch_card_html(state, board=None, feed=[], debug=True)
            state.text = html
            self._flush_watch(state, html)
        except Exception:
            pass

    def register_commands(self) -> None:
        jobs: list[tuple[list[dict], dict | None]] = [
            (USER_BOT_COMMANDS, None),
            (USER_BOT_COMMANDS, {"type": "all_group_chats"}),
            (ADMIN_BOT_COMMANDS, {"type": "all_private_chats"}),
        ]
        for aid in sorted(self.admin_ids):
            jobs.append((ADMIN_BOT_COMMANDS, {"type": "chat", "chat_id": aid}))
        for i, (cmds, scope) in enumerate(jobs):
            if i:
                time.sleep(TG_COMMANDS_GAP)
            try:
                self.tg.set_my_commands(cmds, scope)
            except Exception:
                if scope and scope.get("type") == "chat":
                    continue
                raise

    def run(self) -> None:
        log.info("bot start admins=%s", sorted(self.admin_ids))
        try:
            self.register_commands()
            log.info("setMyCommands ok")
        except Exception:
            log.exception("setMyCommands failed")
        offset = 0
        while True:
            try:
                updates = self.tg.get_updates(offset=offset, timeout=25)
            except Exception:
                log.exception("getUpdates failed")
                time.sleep(GET_UPDATES_FAIL_SLEEP)
                continue
            if updates:
                log.info("updates n=%s", len(updates))
            for upd in updates:
                offset = upd["update_id"] + 1
                keys = [k for k in upd if k != "update_id"]
                log.info("update id=%s keys=%s", upd.get("update_id"), keys)
                if upd.get("my_chat_member"):
                    try:
                        self.handle_added_to_chat(upd)
                    except Exception:
                        log.exception("my_chat_member handler")
                    continue
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text") or ""
                chat = msg.get("chat") or {}
                cid = chat.get("id")
                if cid is None or not text:
                    log.info("skip empty chat=%s text=%r", cid, text)
                    continue
                try:
                    self.handle_text(
                        int(cid),
                        text,
                        message_id=msg.get("message_id"),
                        user_id=(msg.get("from") or {}).get("id"),
                        chat_title=chat.get("title") or "",
                        chat_type=chat.get("type") or "",
                    )
                except Exception as e:
                    log.exception("handle_text chat=%s", cid)
                    try:
                        self._reply(cid, f"错误: {e}")
                    except Exception:
                        pass


def bot_from_env() -> HltvTelegramBot:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or ""
    if not token:
        raise SystemExit("设置 TELEGRAM_BOT_TOKEN")
    session_path = os.environ.get("HLTV_SESSION") or "data/session.json"
    if not Path(session_path).exists():
        raise SystemExit(f"缺少 {session_path}（复制 data/session.example.json 并贴入 Cookie）")
    bump = float(os.environ.get("HLTV_BUMP_SECONDS") or "0")
    raw_admins = os.environ.get("TELEGRAM_ADMIN_IDS") or str(DEFAULT_ADMIN_ID)
    admin_ids: set[int] = set()
    for part in raw_admins.replace(";", ",").split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            admin_ids.add(int(part))
    if not admin_ids:
        admin_ids = {DEFAULT_ADMIN_ID}
    seed = os.environ.get("TELEGRAM_CHAT_ID") or ""
    if seed.strip().lstrip("-").isdigit():
        add_group(int(seed.strip()), "seed")
    return HltvTelegramBot(
        Telegram(token),
        load_session(session_path),
        admin_ids=admin_ids,
        bump_seconds=bump,
    )
