from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("hltv_bot")

from hltv_bot.chats import add_group, group_ids, list_groups, remove_group
from hltv_bot.format import format_match_list, format_telegram
from hltv_bot.http import CloudflareError
from hltv_bot.live import merge_log, snapshot_from_scoreboard
from hltv_bot.matches import fetch_match_meta, fetch_matches
from hltv_bot.scorebot import iter_scorebot, scorebot_base
from hltv_bot.ratelimit import Cooldown
from hltv_bot.session import BrowserSession, load_session, save_cookie
from hltv_bot.snapshot import snapshot_fingerprint
from hltv_bot.telegram_api import Telegram

DEFAULT_ADMIN_ID = 1442477170

HELP = """\
/matches — 今日比赛
/watch — 实时观赛
/bump — 顶到最新
/stop — 停止观赛

管理员：
/allow — 授权本群
/deny — 取消授权
/groups — 已授权群
/cookie — 更新 Cookie
/status — 状态
/debug — 调试（user/chat/admin）
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

USER_BOT_COMMANDS = [
    {"command": "matches", "description": "今日比赛"},
    {"command": "watch", "description": "实时观赛(自动更新)"},
    {"command": "bump", "description": "顶到最新"},
    {"command": "stop", "description": "停止观赛"},
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
class WatchState:
    chat_id: int
    list_id: str
    meta: dict
    message_id: int | None = None
    text: str = ""
    fingerprint: str = ""
    stop: threading.Event = field(default_factory=threading.Event)
    last_bump: float = 0.0
    last_edit: float = 0.0
    last_snap: dict = field(default_factory=dict)
    link: str = "connecting"


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
                self.tg.send_message(
                    chat_id,
                    f"无权限授权本群\n你的 id: <code>{user_id}</code>\nchat: <code>{chat_id}</code>",
                )
                return
        elif cmd in ADMIN_CMDS and not self.is_admin(user_id):
            log.info("deny admin cmd %s user=%s chat=%s", cmd, user_id, chat_id)
            if cmd in {"/debug", "/status", "/groups", "/cookie"}:
                self.tg.send_message(
                    chat_id,
                    f"无权限\n你的 id: <code>{user_id}</code>",
                )
            return
        if cmd not in ADMIN_CMDS | {"/start", "/help"} and not listed and not self.is_admin(user_id):
            log.info("skip cmd=%s chat=%s not in allow-list", cmd, chat_id)
            return
        if cmd.startswith("/") and user_id is not None:
            interval = CMD_COOLDOWN.get(cmd, DEFAULT_CMD_COOLDOWN)
            key = f"{user_id}:{cmd}"
            if not self._cool.allow(key, interval):
                wait = self._cool.remaining(key, interval)
                if cmd in {"/matches", "/matchs", "/match", "/watch", "/bump"}:
                    self.tg.send_message(chat_id, f"稍等 {wait:.0f}s")
                return
        if cmd in ("/start", "/help"):
            self._await_cookie.discard(chat_id)
            if self.is_admin(user_id) or self.chat_allowed(chat_id, user_id=user_id):
                self.tg.send_message(chat_id, HELP)
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
            self._cmd_stop(chat_id)
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
            self.tg.send_message(chat_id, f"Cloudflare 拦了列表页：{e}\n发 /cookie 更新 Cookie")
            return
        if not rows:
            self.tg.send_message(chat_id, "列表是空的（或解析失败）")
            return
        self.tg.send_message(
            chat_id, format_match_list(rows, starred_only=not all_mode)
        )

    def _cmd_watch(self, chat_id: int, arg: str) -> None:
        if not arg:
            self.tg.send_message(chat_id, "用法: /watch 2396932")
            return
        self._stop_watch()
        raw = arg.strip()
        try:
            meta = fetch_match_meta(self.session, raw)
        except CloudflareError as e:
            self.tg.send_message(chat_id, f"详情页 Cloudflare：{e}\n发 /cookie 更新 Cookie")
            return
        list_id = meta.get("scorebotId") or "".join(ch for ch in raw if ch.isdigit())
        if not list_id:
            self.tg.send_message(chat_id, "没有 data-scorebot-id")
            return
        t1, t2 = meta.get("team1") or "?", meta.get("team2") or "?"
        text = f"🔴 <b>LIVE</b>  {t1}  —  {t2}\n连接 {list_id}…"
        msg = self.tg.send_message(chat_id, text)
        state = WatchState(
            chat_id=chat_id,
            list_id=str(list_id),
            meta=meta,
            message_id=msg["message_id"],
            text=text,
            last_bump=time.time(),
        )
        self.watch = state
        self._thread = threading.Thread(target=self._watch_loop, args=(state,), daemon=True)
        self._thread.start()

    def _cmd_bump(self, chat_id: int) -> None:
        w = self.watch
        if not w or w.chat_id != chat_id or not w.text:
            self.tg.send_message(chat_id, "没有正在 watch 的消息")
            return
        msg = self.tg.send_message(chat_id, w.text)
        w.message_id = msg["message_id"]
        w.last_bump = time.time()

    def _cmd_stop(self, chat_id: int) -> None:
        self._stop_watch()
        self.tg.send_message(chat_id, "已停止")

    def _cmd_status(self, chat_id: int) -> None:
        names = self.session.cookie_names()
        w = self.watch
        watch_line = "idle"
        if w and not w.stop.is_set():
            watch_line = f"watching {w.list_id} msg={w.message_id}"
        self.tg.send_message(
            chat_id,
            "\n".join(
                [
                    f"impersonate: {self.session.impersonate}",
                    f"cf_clearance: {'yes' if self.session.has_clearance() else 'NO'}",
                    f"cookies: {', '.join(names) or '(none)'}",
                    f"session: {self.session.path}",
                    watch_line,
                    f"auto-bump: {self.bump_seconds}s" if self.bump_seconds else "auto-bump: off（用 /bump）",
                    f"admins: {', '.join(str(i) for i in sorted(self.admin_ids))}",
                    f"groups: {len(list_groups())}",
                ]
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
            self.tg.send_message(chat_id, "在目标群里发 /allow，或 /allow -100xxxxxxxxxx")
            return
        added = add_group(gid, title)
        log.info("allow chat=%s title=%s added=%s", gid, title, added)
        self.tg.send_message(
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
            self.tg.send_message(chat_id, f"已移除 <code>{gid}</code>")
        else:
            self.tg.send_message(chat_id, f"名单里没有 <code>{gid}</code>")

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
        lines = [
            "<b>debug</b>",
            f"user_id: <code>{user_id}</code>",
            f"chat_id: <code>{chat_id}</code>",
            f"chat_type: {chat_type or '?'}",
            f"title: {chat_title or '-'}",
            f"bot_admin: {self.is_admin(user_id)}",
            f"can_setup: {self.can_setup_chat(chat_id, user_id, chat_type)}",
            f"chat_listed: {listed}",
            f"admins: {', '.join(str(i) for i in sorted(self.admin_ids))}",
            "groups:",
        ]
        if rows:
            for g in rows:
                lines.append(f"  <code>{g.get('id')}</code> {g.get('title') or ''}")
        else:
            lines.append("  (empty)")
        log.info("debug %s", " | ".join(lines))
        self.tg.send_message(chat_id, "\n".join(lines))

    def _cmd_groups(self, chat_id: int) -> None:
        rows = list_groups()
        if not rows:
            self.tg.send_message(chat_id, "还没有授权群。把 bot 拉进群后发 /allow")
            return
        lines = ["授权群"]
        for g in rows:
            lines.append(f"<code>{g.get('id')}</code>  {g.get('title') or ''}")
        self.tg.send_message(chat_id, "\n".join(lines))

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
            self.tg.send_message(
                cid,
                f"已进群 <b>{title}</b>\n发 /allow 加入推送名单",
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
        self.tg.send_message(
            chat_id,
            "把 DevTools → Network → Cookie 整行贴过来（可带 Cookie: 前缀）。\n"
            "发完后会尽量删掉你的消息。取消请发 /status。",
        )

    def _apply_cookie(self, chat_id: int, raw: str, *, message_id: int | None) -> None:
        self._await_cookie.discard(chat_id)
        path = self._session_path()
        save_cookie(path, raw)
        self.session = load_session(path)
        names = self.session.cookie_names()
        if not names:
            self.tg.send_message(chat_id, "Cookie 是空的，没写入有效内容")
            return
        if message_id is not None:
            self.tg.delete_message(chat_id, message_id)
        extra = ""
        if self.watch and not self.watch.stop.is_set():
            extra = "\n正在 watch：新 cookie 下一轮请求会用上；仍 403 就 /stop 再 /watch。"
        self.tg.send_message(
            chat_id,
            "Cookie 已更新\n"
            f"cf_clearance: {'yes' if self.session.has_clearance() else 'NO（请贴完整头）'}\n"
            f"names: {', '.join(names)}"
            + extra,
        )

    def _stop_watch(self) -> None:
        if self.watch:
            self.watch.stop.set()
        self.watch = None

    def _watch_loop(self, state: WatchState) -> None:
        board: dict = {}
        feed: list = []
        try:
            stream = iter_scorebot(
                self.session,
                state.list_id,
                base=scorebot_base(state.meta.get("scorebotUrl")),
            )
            for name, payload in stream:
                if state.stop.is_set() or self.watch is not state:
                    return
                status_changed = False
                if name == "status" and isinstance(payload, dict):
                    new_link = str(payload.get("state") or state.link)
                    status_changed = new_link != state.link
                    state.link = new_link
                elif name == "scoreboard" and isinstance(payload, dict):
                    board = payload
                elif name == "log":
                    feed = merge_log(feed, payload)
                else:
                    continue
                snap = snapshot_from_scoreboard(board, meta=state.meta, log=feed)
                snap["link"] = state.link
                fp = snapshot_fingerprint(snap) + "|" + state.link
                if fp == state.fingerprint and not status_changed:
                    continue
                text = format_telegram(snap)
                state.text = text
                state.last_snap = snap
                state.fingerprint = fp
                now = time.time()
                force = status_changed or any(
                    s in text for s in ("🔥 3K", "💥 4K", "⭐ ACE", "🏁")
                )
                if now - state.last_edit < MIN_EDIT_INTERVAL and not force:
                    continue
                if (
                    self.bump_seconds
                    and state.message_id
                    and now - state.last_bump >= self.bump_seconds
                ):
                    msg = self.tg.send_message(state.chat_id, text)
                    state.message_id = msg["message_id"]
                    state.last_bump = now
                    state.last_edit = now
                    continue
                if state.message_id:
                    try:
                        self.tg.edit_message(state.chat_id, state.message_id, text)
                    except Exception:
                        msg = self.tg.send_message(state.chat_id, text)
                        state.message_id = msg["message_id"]
                        state.last_bump = now
                    state.last_edit = now
        except CloudflareError as e:
            self._mark_watch_down(state, "disconnected")
            self.tg.send_message(state.chat_id, f"Scorebot Cloudflare：{e}\n/cookie 更新后 /watch")
        except Exception as e:
            self._mark_watch_down(state, "disconnected")
            if not state.stop.is_set():
                log.info("watch ended: %s", e)

    def _mark_watch_down(self, state: WatchState, link: str) -> None:
        state.link = link
        snap = dict(state.last_snap or {"live": True, "teams": [], "log": []})
        snap["link"] = link
        try:
            text = format_telegram(snap)
            state.text = text
            if state.message_id:
                self.tg.edit_message(state.chat_id, state.message_id, text)
        except Exception:
            pass

    def register_commands(self) -> None:
        self.tg.set_my_commands(USER_BOT_COMMANDS)
        self.tg.set_my_commands(USER_BOT_COMMANDS, {"type": "all_group_chats"})
        self.tg.set_my_commands(ADMIN_BOT_COMMANDS, {"type": "all_private_chats"})
        for aid in self.admin_ids:
            try:
                self.tg.set_my_commands(
                    ADMIN_BOT_COMMANDS, {"type": "chat", "chat_id": aid}
                )
            except Exception:
                pass

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
                time.sleep(3)
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
                        self.tg.send_message(cid, f"错误: {e}")
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
