from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from hltv_bot.format import format_telegram
from hltv_bot.http import CloudflareError
from hltv_bot.live import merge_log, snapshot_from_scoreboard
from hltv_bot.matches import fetch_match_meta, fetch_matches
from hltv_bot.scorebot import iter_scorebot, scorebot_base
from hltv_bot.session import BrowserSession, load_session, save_cookie
from hltv_bot.snapshot import snapshot_fingerprint
from hltv_bot.telegram_api import Telegram

HELP = """\
/matches — 今日比赛列表
/watch id — 盯这条的 realtime，发一条消息并持续 edit
/bump — 再发一条新消息，之后 edit 这条（避免被讨论刷下去）
/stop — 停止
/status — cookie / 伪装 / 是否在看
/cookie — 更新 Cookie（下一条消息贴 DevTools 的 Cookie 头）
"""


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
        allowed_chat: str | None = None,
        bump_seconds: float = 0.0,
    ):
        self.tg = tg
        self.session = session
        self.allowed_chat = str(allowed_chat) if allowed_chat else None
        self.bump_seconds = bump_seconds
        self.watch: WatchState | None = None
        self._thread: threading.Thread | None = None
        self._await_cookie: set[int] = set()

    def allowed(self, chat_id: int) -> bool:
        if not self.allowed_chat:
            return True
        return str(chat_id) == self.allowed_chat

    def handle_text(self, chat_id: int, text: str, *, message_id: int | None = None) -> None:
        if not self.allowed(chat_id):
            return
        parts = text.strip().split()
        cmd = (parts[0].split("@")[0] if parts else "").lower()
        arg = " ".join(parts[1:]) if len(parts) > 1 else ""
        if chat_id in self._await_cookie and not cmd.startswith("/"):
            self._apply_cookie(chat_id, text, message_id=message_id)
            return
        if cmd in ("/start", "/help"):
            self._await_cookie.discard(chat_id)
            self.tg.send_message(chat_id, HELP)
        elif cmd == "/matches":
            self._await_cookie.discard(chat_id)
            self._cmd_matches(chat_id)
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

    def _cmd_matches(self, chat_id: int) -> None:
        try:
            rows = fetch_matches(self.session)
        except CloudflareError as e:
            self.tg.send_message(chat_id, f"Cloudflare 拦了列表页：{e}\n发 /cookie 更新 Cookie")
            return
        if not rows:
            self.tg.send_message(chat_id, "列表是空的（或解析失败）")
            return
        lines = ["比赛"]
        for r in rows[:15]:
            flag = "LIVE " if r.get("live") == "1" else ""
            lines.append(f"{flag}{r['id']}  {r['title']}")
        lines.append("\n/watch id")
        self.tg.send_message(chat_id, "\n".join(lines))

    def _cmd_watch(self, chat_id: int, arg: str) -> None:
        if not arg:
            self.tg.send_message(chat_id, "用法: /watch 2396932")
            return
        self._stop_watch()
        try:
            meta = fetch_match_meta(self.session, arg.strip())
        except CloudflareError as e:
            self.tg.send_message(chat_id, f"详情页 Cloudflare：{e}\n发 /cookie 更新 Cookie")
            return
        list_id = meta.get("scorebotId") or "".join(ch for ch in arg if ch.isdigit())
        if not list_id:
            self.tg.send_message(chat_id, "没有 data-scorebot-id")
            return
        t1, t2 = meta.get("team1") or "?", meta.get("team2") or "?"
        text = f"LIVE | {t1} vs {t2}\n连接 Scorebot {list_id}…\n\n讨论多了发 /bump"
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
                ]
            ),
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
            for name, payload in iter_scorebot(
                self.session, state.list_id, base=scorebot_base(state.meta.get("scorebotUrl"))
            ):
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
                msg = upd.get("message") or upd.get("edited_message") or {}
                text = msg.get("text") or ""
                chat = (msg.get("chat") or {}).get("id")
                if chat is None or not text:
                    continue
                try:
                    self.handle_text(int(chat), text, message_id=msg.get("message_id"))
                except Exception as e:
                    try:
                        self.tg.send_message(chat, f"错误: {e}")
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
    return HltvTelegramBot(
        Telegram(token),
        load_session(session_path),
        allowed_chat=os.environ.get("TELEGRAM_CHAT_ID") or None,
        bump_seconds=bump,
    )
