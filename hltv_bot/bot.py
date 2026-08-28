from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from hltv_bot.chats import add_group, group_ids, list_groups, remove_group
from hltv_bot.fixtures import MOCK_MATCHES, iter_mock_scorebot, mock_meta
from hltv_bot.format import format_match_list, format_telegram
from hltv_bot.http import CloudflareError
from hltv_bot.live import merge_log, snapshot_from_scoreboard
from hltv_bot.matches import fetch_match_meta, fetch_matches
from hltv_bot.scorebot import iter_scorebot, scorebot_base
from hltv_bot.settings import is_real, parse_real_arg, set_real
from hltv_bot.session import BrowserSession, load_session, save_cookie
from hltv_bot.snapshot import snapshot_fingerprint
from hltv_bot.telegram_api import Telegram

DEFAULT_ADMIN_ID = 1442477170

HELP = """\
/matches — 有星赛事（分组 / 星级 / 开赛时间 UTC+8）
/matchs — 同上
/matches all — 全部比赛
/watch id — 盯这条 realtime，发一条消息并持续 edit
/bump — 再发一条新消息并 edit（避免被讨论刷下去）
/stop — 停止

管理员：
/allow — 把当前群加入推送名单（把 bot 拉进群后在群里发）
/deny — 从名单去掉当前群（或 /deny chat_id）
/groups — 已授权群
/status — cookie / 伪装
/cookie — 更新 Cookie
/real — 关闭真实请求（默认，用测试数据）
/real 1 — 开启真实 HLTV 请求
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
        "/real",
    }
)


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

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and int(user_id) in self.admin_ids

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
        if chat_id in self._await_cookie and not cmd.startswith("/"):
            if not self.is_admin(user_id):
                return
            self._apply_cookie(chat_id, text, message_id=message_id)
            return
        if cmd in ADMIN_CMDS and not self.is_admin(user_id):
            return
        if cmd not in ADMIN_CMDS | {"/start", "/help"} and not self.chat_allowed(
            chat_id, user_id=user_id
        ):
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
        elif cmd == "/real":
            self._cmd_real(chat_id, arg)

    def _cmd_matches(self, chat_id: int, arg: str = "") -> None:
        all_mode = arg.strip().lower() in {"all", "全部", "*", "full"}
        if is_real():
            try:
                rows = fetch_matches(self.session)
            except CloudflareError as e:
                self.tg.send_message(chat_id, f"Cloudflare 拦了列表页：{e}\n发 /cookie 更新 Cookie")
                return
        else:
            rows = list(MOCK_MATCHES)
        if not rows:
            self.tg.send_message(chat_id, "列表是空的（或解析失败）")
            return
        note = "" if is_real() else "🧪 <i>测试数据 · /real 1 接真源</i>\n\n"
        self.tg.send_message(
            chat_id, note + format_match_list(rows, starred_only=not all_mode)
        )

    def _cmd_watch(self, chat_id: int, arg: str) -> None:
        if not arg:
            self.tg.send_message(chat_id, "用法: /watch 2396932")
            return
        self._stop_watch()
        raw = arg.strip()
        if is_real():
            try:
                meta = fetch_match_meta(self.session, raw)
            except CloudflareError as e:
                self.tg.send_message(chat_id, f"详情页 Cloudflare：{e}\n发 /cookie 更新 Cookie")
                return
        else:
            digits = "".join(ch for ch in raw if ch.isdigit()) or "2396932"
            meta = mock_meta(digits)
        list_id = meta.get("scorebotId") or "".join(ch for ch in raw if ch.isdigit())
        if not list_id:
            self.tg.send_message(chat_id, "没有 data-scorebot-id")
            return
        t1, t2 = meta.get("team1") or "?", meta.get("team2") or "?"
        mode = "" if is_real() else "\n🧪 测试数据"
        text = f"🔴 <b>LIVE</b>  {t1}  —  {t2}{mode}\n连接 {list_id}…"
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
                    f"real: {'on' if is_real() else 'off（测试数据）'}",
                ]
            ),
        )

    def _cmd_real(self, chat_id: int, arg: str) -> None:
        parsed = parse_real_arg(arg)
        if parsed is None:
            self.tg.send_message(chat_id, "用法: /real 关闭真实请求 · /real 1 开启")
            return
        on = set_real(parsed)
        if on:
            self.tg.send_message(chat_id, "已开启真实 HLTV 请求")
        else:
            self.tg.send_message(chat_id, "已关闭真实请求，/matches /watch 用测试数据")

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
        if new not in ("member", "administrator") or old in ("member", "administrator"):
            return
        from_id = (member.get("from") or {}).get("id")
        cid = chat.get("id")
        title = chat.get("title") or ""
        if cid is None or not self.is_admin(from_id):
            return
        self.tg.send_message(
            cid,
            f"已进群 <b>{title}</b>\n管理员发 /allow 加入推送名单",
        )

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
        log: list = []
        try:
            if is_real():
                stream = iter_scorebot(
                    self.session,
                    state.list_id,
                    base=scorebot_base(state.meta.get("scorebotUrl")),
                )
            else:
                stream = iter_mock_scorebot(state.list_id)
            for name, payload in stream:
                if state.stop.is_set() or self.watch is not state:
                    return
                if name == "scoreboard" and isinstance(payload, dict):
                    board = payload
                elif name == "log":
                    log = merge_log(log, payload)
                else:
                    continue
                snap = snapshot_from_scoreboard(board, meta=state.meta, log=log)
                fp = snapshot_fingerprint(snap)
                if fp == state.fingerprint:
                    continue
                text = format_telegram(snap)
                state.text = text
                state.fingerprint = fp
                now = time.time()
                if (
                    self.bump_seconds
                    and state.message_id
                    and now - state.last_bump >= self.bump_seconds
                ):
                    msg = self.tg.send_message(state.chat_id, text)
                    state.message_id = msg["message_id"]
                    state.last_bump = now
                    continue
                if state.message_id:
                    try:
                        self.tg.edit_message(state.chat_id, state.message_id, text)
                    except Exception:
                        msg = self.tg.send_message(state.chat_id, text)
                        state.message_id = msg["message_id"]
                        state.last_bump = now
        except CloudflareError as e:
            self.tg.send_message(state.chat_id, f"Scorebot Cloudflare：{e}\n/cookie 更新后 /watch")
        except Exception as e:
            if not state.stop.is_set():
                self.tg.send_message(state.chat_id, f"watch 结束: {e}")

    def run(self) -> None:
        offset = 0
        while True:
            try:
                updates = self.tg.get_updates(offset=offset, timeout=25)
            except Exception:
                time.sleep(3)
                continue
            for upd in updates:
                offset = upd["update_id"] + 1
                if upd.get("my_chat_member"):
                    try:
                        self.handle_added_to_chat(upd)
                    except Exception:
                        pass
                    continue
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text") or ""
                chat = msg.get("chat") or {}
                cid = chat.get("id")
                if cid is None or not text:
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
