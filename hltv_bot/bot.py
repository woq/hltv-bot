"""Telegram bot: API match/score alerts and Tier1/Major event reminders.

Chrome keeper and the live scoreboard card stay on the archive/chrome-full branch.
This process polls HLTV HTML and does not start Chrome.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path

from hltv_bot.chats import add_group, group_ids, list_groups, remove_group
from hltv_bot.events import (
    EVENTS_CACHE_TTL,
    classify_event_tier,
    classify_tier,
    fetch_events,
    filter_and_sort_events,
    format_events_html,
    tier_label,
    tier_rank,
)
from hltv_bot.format import format_match_list, h
from hltv_bot.http import CloudflareError
from hltv_bot.matches import fetch_matches, prepare_match_list
from hltv_bot.ratelimit import Cooldown
from hltv_bot.reminders import CST, RemindConfig, choose_poll_wait, empty_state, plan_reminders
from hltv_bot.session import BrowserSession, load_session
from hltv_bot.settings import notify_config, update_settings
from hltv_bot.telegram_api import Telegram

log = logging.getLogger("hltv_bot")

DEFAULT_ADMIN_ID = 1442477170
MSG_TTL = 30.0
GET_UPDATES_FAIL_SLEEP = 3.0
TG_COMMANDS_GAP = 0.4
# One /matches fetch covers every live BO1/BO3/BO5. That is the score clock.
MATCH_PAGE_MIN = 3.0
MATCH_PAGE_MAX = 5.0
CF_ALERT_EVERY = 1800.0
STATE_PATH = Path("data/reminders.json")

CMD_COOLDOWN = {
    "/matches": 8.0,
    "/matchs": 8.0,
    "/match": 8.0,
    "/events": 8.0,
    "/cookie": 3.0,
}
DEFAULT_CMD_COOLDOWN = 1.2

HELP = """\
<b>hltv-bot</b>
时间 <code>UTC+8</code>。提醒默认无声，发到通知群，同时私聊管理员。

• <code>/matches</code> — 比赛列表（<code>t2</code> / <code>t3</code> / <code>all</code> / <code>text</code>）
• <code>/events</code> — Major / T1 赛事

比分只看赛程总页。进入 Live 时 0:0 只发一次，当作预告。同一张图里两边的回合分只会变大。BO3 / BO5 写出当前地图和系列分。新的一条比分会删掉这场上一条。

一个比赛日是 UTC+8 早上 10:00 到次日 10:00，跨过凌晨，用来装国外晚上的比赛。赛程每天两次：10:00 看这一整日，20:00 看这一日里还没开的，含次日凌晨。不按比赛自己的开赛钟点。

赛事另按开赛倒计时，只推 Major / T1：进入窗口、剩 1 天、最后 N 小时。默认前 7 天到前 6 小时，<code>/window 7 6</code> 可改。

<b>补充监控</b>
• <code>/follow 比赛id</code> — 单场。赛事本身不够默认条件时用
• <code>/unfollow 比赛id</code>
• <code>/cover 赛事id</code> — 打开这一赛事每个比赛日的全部比赛
• <code>/uncover 赛事id</code>
• <code>/ignore 比赛id</code> — 从默认、单场、整赛事里摘掉一场

<b>管理员</b>
• <code>/groups</code> — 通知群
• <code>/allow</code> — 把本群加入通知
• <code>/deny</code> — 移出通知
• <code>/follow 比赛id</code> — 单场加入比分监控
• <code>/unfollow 比赛id</code> — 取消单场
• <code>/cover 赛事id</code> — 批量打开该赛事每个比赛日
• <code>/uncover 赛事id</code> — 关闭该赛事
• <code>/ignore 比赛id</code> — 这一场不推
• <code>/unignore 比赛id</code> — 恢复这场
• <code>/watch</code> — 本群打开多场比分（Major/T1 和 /cover）
• <code>/stop</code> — 本群关闭比分
• <code>/follow on</code> — 本群打开单场比分
• <code>/track</code> — 打开赛程和赛事提醒
• <code>/untrack</code> — 关闭赛程和赛事提醒
• <code>/digest 10 20</code> — 赛程提醒钟点，UTC+8
• <code>/stars 1</code> — 默认比赛的最低星级
• <code>/silent</code> — 无声开关，默认开
• <code>/cookie</code> — 更新 Cookie
• <code>/status</code>
"""

ADMIN_CMDS = frozenset(
    {
        "/allow",
        "/deny",
        "/groups",
        "/window",
        "/digest",
        "/follow",
        "/unfollow",
        "/cover",
        "/uncover",
        "/stars",
        "/silent",
        "/ignore",
        "/unignore",
        "/stop",
        "/watch",
        "/track",
        "/untrack",
        "/cookie",
        "/updatecookie",
        "/update_cookie",
        "/status",
        "/debug",
    }
)

BOT_COMMANDS = [
    {"command": "matches", "description": "比赛列表"},
    {"command": "events", "description": "Major/T1 赛事"},
    {"command": "hltv", "description": "用法"},
    {"command": "allow", "description": "加入通知群"},
    {"command": "deny", "description": "移出通知群"},
    {"command": "groups", "description": "通知群"},
    {"command": "ignore", "description": "忽略一场比赛"},
    {"command": "unignore", "description": "恢复一场比赛"},
    {"command": "stop", "description": "本群关闭比分"},
    {"command": "watch", "description": "本群打开多场比分"},
    {"command": "track", "description": "打开赛程和赛事提醒"},
    {"command": "untrack", "description": "关闭赛程和赛事提醒"},
    {"command": "follow", "description": "单场加入比分监控"},
    {"command": "unfollow", "description": "取消单场监控"},
    {"command": "cover", "description": "打开整赛事每个比赛日"},
    {"command": "uncover", "description": "关闭整赛事监控"},
    {"command": "digest", "description": "赛程提醒钟点 UTC+8"},
    {"command": "stars", "description": "默认比赛的最低星级"},
    {"command": "silent", "description": "无声通知 开/关"},
    {"command": "cookie", "description": "更新 Cookie"},
    {"command": "status", "description": "状态"},
]


def command_jobs(admin_ids: set[int], groups: set[int]) -> list[tuple[list[dict], dict | None]]:
    """One full menu for every chat. Scope splits are cleared separately."""
    del admin_ids, groups
    return [(BOT_COMMANDS, None)]


def command_scope_clears(admin_ids: set[int], groups: set[int]) -> list[dict]:
    """Drop older per-audience menus so they cannot hide the full list."""
    scopes: list[dict] = [
        {"type": "all_private_chats"},
        {"type": "all_group_chats"},
        {"type": "all_chat_administrators"},
    ]
    for aid in sorted(admin_ids):
        scopes.append({"type": "chat", "chat_id": int(aid)})
        for gid in sorted(groups):
            scopes.append({"type": "chat_member", "chat_id": int(gid), "user_id": int(aid)})
    return scopes


def _load_state(path: Path) -> dict:
    if not path.exists():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    data.setdefault("matches", {})
    data.setdefault("events", {})
    return data


def _save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


class HltvTelegramBot:
    def __init__(
        self,
        tg: Telegram,
        session: BrowserSession,
        *,
        admin_ids: set[int] | None = None,
        bump_seconds: float = 0.0,
        cdp_url: str | None = None,
        keeper_url: str | None = None,
        export_every: float = 300.0,
        state_path: Path | None = None,
        settings_path: Path | None = None,
        poll_seconds: float = MATCH_PAGE_MIN,
    ):
        self.tg = tg
        self.session = session
        self.admin_ids = admin_ids or {DEFAULT_ADMIN_ID}
        self.bump_seconds = bump_seconds
        self.cdp_url = cdp_url
        self.keeper_url = keeper_url
        self.export_every = float(export_every)
        self.state_path = state_path or STATE_PATH
        self.settings_path = settings_path
        self.poll_seconds = float(poll_seconds)
        self._await_cookie: set[int] = set()
        self._cool = Cooldown()
        self.msg_ttl = MSG_TTL
        self._can_delete_cache: dict[int, tuple[float, bool]] = {}
        self.started_at = time.time()
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._state = _load_state(self.state_path)
        self.last_poll_at = 0.0
        self.last_error = ""
        self._cf_alerted_at = 0.0
        self.keeper_cdp = "off"
        self.keeper_title = ""
        self.keeper_url_seen = ""
        self.keeper_exported_at = 0.0
        self.keeper_clearance = False
        self.keeper_challenge = False
        self._was_challenge = False
        self._challenge_alerted_at = 0.0
        self._cdp_down_alerted_at = 0.0
        self._keeper_stop = threading.Event()
        self.watch = None
        self._event_rows: list | None = None
        self._events_retry_at = 0.0
        self._list_rows: list[dict] = []
        self._list_at = 0.0
        self._list_next = 0.0
        self._events_next = 0.0
        self._wake = threading.Event()

    def can_delete_in_chat(self, chat_id: int) -> bool:
        cid = int(chat_id)
        if cid > 0:
            return True
        now = time.monotonic()
        cached = self._can_delete_cache.get(cid)
        if cached and now - cached[0] < 300.0:
            return cached[1]
        can = self.tg.bot_can_delete_messages(cid)
        self._can_delete_cache[cid] = (now, can)
        return can

    def is_admin(self, user_id: int | None) -> bool:
        return user_id is not None and int(user_id) in self.admin_ids

    def can_setup_chat(self, chat_id: int, user_id: int | None, chat_type: str) -> bool:
        if self.is_admin(user_id):
            return True
        if chat_type not in ("group", "supergroup"):
            return False
        if user_id:
            st = self.tg.chat_member_status(chat_id, int(user_id))
            if st in ("creator", "administrator"):
                return True
        return bool(self.tg.chat_admin_user_ids(chat_id) & self.admin_ids)

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
            if self.is_admin(user_id):
                self._apply_cookie(chat_id, text, message_id=message_id)
            return
        if cmd in {"/allow", "/deny"}:
            if not self.can_setup_chat(chat_id, user_id, chat_type):
                self._reply(chat_id, f"无权限授权本群\n你的 id: <code>{user_id}</code>\nchat: <code>{chat_id}</code>")
                return
        elif cmd in ADMIN_CMDS and not self.is_admin(user_id):
            if cmd in {"/debug", "/status", "/groups", "/cookie"}:
                self._reply(chat_id, f"无权限\n你的 id: <code>{user_id}</code>")
            return
        if cmd not in ADMIN_CMDS | {"/start", "/help", "/hltv"} and not listed and not self.is_admin(user_id):
            return
        if (
            cmd.startswith("/")
            and cmd not in {"/events", "/event"}
            and message_id is not None
            and self.can_delete_in_chat(chat_id)
        ):
            self._schedule_delete(chat_id, int(message_id))
        if cmd.startswith("/") and user_id is not None:
            interval = CMD_COOLDOWN.get(cmd, DEFAULT_CMD_COOLDOWN)
            key = f"{user_id}:{cmd}"
            if not self._cool.allow(key, interval):
                return
        if cmd in ("/start", "/help", "/hltv"):
            self._await_cookie.discard(chat_id)
            if self.is_admin(user_id) or self.chat_allowed(chat_id, user_id=user_id):
                self._reply_guide(chat_id)
        elif cmd == "/allow":
            self._cmd_allow(chat_id, arg, chat_title=chat_title, chat_type=chat_type)
        elif cmd == "/deny":
            self._cmd_deny(chat_id, arg)
        elif cmd == "/groups":
            self._cmd_groups(chat_id)
        elif cmd in ("/matches", "/matchs", "/match"):
            self._await_cookie.discard(chat_id)
            self._cmd_matches(chat_id, arg)
        elif cmd in ("/events", "/event"):
            self._await_cookie.discard(chat_id)
            self._cmd_events(chat_id, arg)
        elif cmd == "/window":
            self._cmd_window(chat_id, arg)
        elif cmd == "/digest":
            self._cmd_digest(chat_id, arg)
        elif cmd == "/follow":
            self._cmd_follow(chat_id, arg)
        elif cmd == "/unfollow":
            self._cmd_id_unlist(chat_id, arg, key="followed", usage="/unfollow 比赛id")
            self._kick()
        elif cmd == "/cover":
            if arg.strip():
                self._cmd_id_list(chat_id, arg, key="covered", title="赛事监控", usage="/cover 赛事id")
                self._kick()
            else:
                self._cmd_cover_list(chat_id)
        elif cmd == "/uncover":
            self._cmd_id_unlist(chat_id, arg, key="covered", usage="/uncover 赛事id")
            self._kick()
        elif cmd == "/stars":
            self._cmd_stars(chat_id, arg)
        elif cmd == "/silent":
            self._cmd_silent(chat_id, arg)
        elif cmd == "/ignore":
            self._cmd_ignore(chat_id, arg)
        elif cmd == "/unignore":
            self._cmd_unignore(chat_id, arg)
        elif cmd == "/stop":
            self._cmd_stop_watch(chat_id)
        elif cmd == "/watch":
            self._cmd_watch(chat_id, arg)
        elif cmd == "/track":
            self._cmd_track(chat_id)
        elif cmd == "/untrack":
            self._cmd_untrack(chat_id)
        elif cmd == "/status":
            self._await_cookie.discard(chat_id)
            self._cmd_status(chat_id)
        elif cmd in ("/cookie", "/updatecookie", "/update_cookie"):
            self._cmd_cookie(chat_id, arg, message_id=message_id)
        elif cmd == "/debug":
            self._cmd_debug(chat_id, user_id=user_id, chat_title=chat_title, chat_type=chat_type)

    def _saved(self) -> dict:
        if self.settings_path is None:
            return notify_config()
        return notify_config(self.settings_path)

    def _write_settings(self, values: dict) -> None:
        if self.settings_path is None:
            update_settings(values)
        else:
            update_settings(values, self.settings_path)

    def _cfg(self) -> RemindConfig:
        raw = self._saved()
        return RemindConfig(
            event_days=int(raw["event_days"]),
            event_hours=int(raw["event_hours"]),
            min_stars=int(raw["min_stars"]),
            watch=bool(raw.get("score_multi") or raw.get("score_single")),
            event_watch=bool(raw.get("event_watch", True)),
            ignored=frozenset(raw.get("ignored") or []),
            followed=frozenset(raw.get("followed") or []),
            covered=frozenset(raw.get("covered") or []),
            score_multi=frozenset(raw.get("score_multi") or []),
            score_single=frozenset(raw.get("score_single") or []),
            digest_morning=int(raw.get("digest_morning") or 10),
            digest_evening=int(raw.get("digest_evening") or 20),
        )

    def _silent(self) -> bool:
        return bool(self._saved().get("silent", True))

    def _quiet(self, ids: list[str] | None = None, *, all_matches: bool = False) -> None:
        with self._state_lock:
            if all_matches:
                self._state["quiet_all"] = True
            if ids:
                have = {str(x) for x in (self._state.get("quiet_ids") or [])}
                have.update(ids)
                self._state["quiet_ids"] = sorted(have)
            _save_state(self._state, self.state_path)

    def _cmd_matches(self, chat_id: int, arg: str) -> None:
        raw = arg.strip().lower()
        if "all" in raw or "全部" in raw or "*" in raw:
            tier = "Other"
        elif "t3" in raw:
            tier = "T3"
        elif "t2" in raw:
            tier = "T2"
        else:
            tier = "T1"
        try:
            rows = fetch_matches(self.session)
        except CloudflareError as e:
            self._reply(chat_id, f"Cloudflare 拦了列表页：{e}\n发 /cookie 更新 Cookie")
            return
        rows = prepare_match_list(rows, datetime.now(CST))
        min_stars = self._cfg().min_stars

        def _stars_of(row: dict) -> int:
            try:
                return int(row.get("stars") or 0)
            except (TypeError, ValueError):
                return 0

        rows = [row for row in rows if _stars_of(row) >= min_stars]
        if tier != "Other":
            floor = tier_rank(tier)
            rows = [
                r
                for r in rows
                if tier_rank(classify_event_tier(r.get("event") or "", int(r.get("stars") or 0))) <= floor
            ]
        if not rows:
            hint = "发 /matches all 看其他赛事。" if tier != "Other" else ""
            self._reply(chat_id, f"暂无 {min_stars} 星及以上的比赛。{hint}".strip())
            return
        if "text" in raw or "txt" in raw:
            self._reply(chat_id, format_match_list(rows, starred_only=False))
            return
        shown = rows[:12]
        caption = f"<b>比赛</b>  {len(shown)} 场 · UTC+8"
        if len(rows) > len(shown):
            caption += f"\n<i>共 {len(rows)} 场，图里是前 {len(shown)} 场</i>"
        caption += "\n<i>/matches all 看全部</i>"
        self._reply_card(chat_id, {"view": "matches", "rows": shown}, caption, format_match_list(rows, starred_only=False))

    def _cmd_events(self, chat_id: int, arg: str) -> None:
        raw = arg.strip().lower()
        if "all" in raw or "全部" in raw:
            tiers = ("Major", "T1", "T2", "T3", "Other")
        elif "t2" in raw:
            tiers = ("Major", "T1", "T2")
        else:
            tiers = ("Major", "T1")
        try:
            rows = filter_and_sort_events(fetch_events(self.session), allowed_tiers=tiers)
        except CloudflareError as e:
            self._reply(chat_id, f"Cloudflare 拦了赛事页：{e}\n发 /cookie 更新 Cookie")
            return
        if "text" in raw or "txt" in raw:
            self._reply(chat_id, format_events_html(rows), keep=True)
            return
        from hltv_bot.events import country_code_to_emoji, format_event_date_range

        shown = rows[:8]
        card_rows = []
        for ev in shown:
            card_rows.append(
                {
                    "id": str(ev.get("id") or ""),
                    "name": ev.get("name") or "",
                    "tier": ev.get("tier") or "",
                    "logo_url": ev.get("logo_url") or "",
                    "flag": country_code_to_emoji(str(ev.get("country_code") or "")),
                    "location": ev.get("location") or "",
                    "when": format_event_date_range(ev.get("start_ts") or 0, ev.get("end_ts") or 0),
                    "prize": (ev.get("prize") or "").strip(),
                }
            )
        caption = f"<b>赛事</b>\n{len(shown)} 场\n<i>/events all 查看全部赛事</i>"
        self._reply_card(chat_id, {"view": "events", "rows": card_rows}, caption, format_events_html(rows), keep=True)

    def _cmd_window(self, chat_id: int, arg: str) -> None:
        parts = arg.split()
        cfg = self._cfg()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            self._reply(
                chat_id,
                "用法 <code>/window 天 小时</code>\n"
                f"当前开赛前 <b>{cfg.event_days}</b> 天，直到前 <b>{cfg.event_hours}</b> 小时",
            )
            return
        days, hours = int(parts[0]), int(parts[1])
        if not (1 <= days <= 60 and 1 <= hours < days * 24):
            self._reply(chat_id, "天数 1–60，小时要小于天数×24")
            return
        self._write_settings({"event_days": days, "event_hours": hours})
        self._reply(chat_id, f"赛事提醒：开赛前 <b>{days}</b> 天，直到前 <b>{hours}</b> 小时")

    def _cmd_digest(self, chat_id: int, arg: str) -> None:
        parts = arg.split()
        cfg = self._cfg()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            self._reply(
                chat_id,
                "用法 <code>/digest 10 20</code>\n"
                f"当前 <code>{cfg.digest_morning:02d}:00</code> 和 <code>{cfg.digest_evening:02d}:00</code> UTC+8",
            )
            return
        morning, evening = int(parts[0]), int(parts[1])
        if not (0 <= morning < evening <= 23):
            self._reply(chat_id, "两个钟点要在 0–23，早上早于晚上")
            return
        self._write_settings({"digest_morning": morning, "digest_evening": evening})
        self._kick()
        self._reply(chat_id, f"赛程提醒 <b>{morning:02d}:00</b> 和 <b>{evening:02d}:00</b> UTC+8")

    def _reply_guide(self, chat_id: int) -> None:
        cfg = self._cfg()
        self._reply_card(
            chat_id,
            {"view": "guide", "morning": cfg.digest_morning, "evening": cfg.digest_evening},
            HELP,
            HELP,
        )

    def _kick(self) -> None:
        self._list_next = 0.0
        self._wake.set()

    def _cmd_cover_list(self, chat_id: int) -> None:
        try:
            rows = fetch_events(self.session)
        except CloudflareError as e:
            self._reply(chat_id, f"Cloudflare 拦了赛事页：{e}\n发 /cookie 更新 Cookie")
            return
        except Exception as e:
            self._reply(chat_id, f"赛事列表失败：{h(e)}")
            return
        now = datetime.now(CST)
        today = now.timestamp()
        picked = []
        for ev in rows:
            end_ts = int(ev.get("end_ts") or ev.get("start_ts") or 0)
            if end_ts and end_ts < today - 86400 and not ev.get("live"):
                continue
            picked.append(ev)
        picked.sort(key=lambda ev: (0 if ev.get("live") else 1, int(ev.get("start_ts") or 0)))
        covered = set(self._cfg().covered)
        shown = picked[:12]
        lines = ["<b>赛事</b>", "发 <code>/cover 赛事id</code> 批量打开"]
        if covered:
            lines.append("已打开 " + " ".join(f"<code>{h(eid)}</code>" for eid in sorted(covered)))
        for ev in shown:
            name = ev.get("name") or ""
            opened = str(ev.get("id") or "") in covered
            lines.append(f"<b>{h(tier_label(classify_tier(name)))}</b>")
            lines.append(f"<b>{h(name)}</b>")
            lines.append(f"<code>{h(ev.get('id') or '')}</code>" + ("  已打开" if opened else ""))
        if len(picked) > len(shown):
            lines.append(f"<i>共 {len(picked)} 个，这里是前 {len(shown)} 个</i>")
        text = "\n".join(lines)
        card_rows = []
        for ev in shown[:8]:
            card_rows.append(
                {
                    "id": str(ev.get("id") or ""),
                    "name": ev.get("name") or "",
                    "tier": classify_tier(ev.get("name") or ""),
                    "when": "已打开" if str(ev.get("id") or "") in covered else "",
                    "flag": "",
                    "location": (ev.get("location") or "").strip(),
                    "when": "",
                    "prize": "",
                    "logo_url": ev.get("logo_url") or "",
                }
            )
        self._reply_card(chat_id, {"view": "events", "rows": card_rows}, text, text)

    def _score_chats(self, key: str) -> list[str]:
        return [str(item) for item in (self._saved().get(key) or [])]

    def _write_score_chats(self, chat_id: int, *, multi: bool | None = None, single: bool | None = None) -> None:
        cid = str(int(chat_id))

        def apply(ids: list[str], flag: bool | None) -> list[str]:
            if flag is None:
                return ids
            if flag and cid not in ids:
                ids.append(cid)
            if not flag:
                ids = [item for item in ids if item != cid]
            return ids

        self._write_settings(
            {
                "score_multi": apply(self._score_chats("score_multi"), multi),
                "score_single": apply(self._score_chats("score_single"), single),
            }
        )

    def _cmd_follow(self, chat_id: int, arg: str) -> None:
        raw = arg.strip().lower()
        if raw in {"on", "开", "开启"}:
            self._write_score_chats(chat_id, single=True)
            self._kick()
            self._reply(chat_id, "本群已打开单场比分。只推到这个群，跟过的比赛有变化才发。")
            return
        if raw in {"off", "关", "关闭"}:
            self._write_score_chats(chat_id, single=False)
            self._kick()
            self._reply(chat_id, "本群已关闭单场比分。多场用 <code>/watch</code>。")
            return
        self._cmd_id_list(
            chat_id,
            arg,
            key="followed",
            title="单场监控",
            usage="/follow 比赛id",
            tail="比分只推到本群。其它群要自己发 <code>/follow on</code>。",
        )
        if any(part.isdigit() for part in arg.split()):
            self._write_score_chats(chat_id, single=True)
            self._kick()

    def _cmd_id_list(self, chat_id: int, arg: str, *, key: str, title: str, usage: str, tail: str = "") -> None:
        ids = [p for p in arg.split() if p.isdigit()]
        current = list(self._saved().get(key) or [])
        if not ids:
            if not current:
                self._reply(chat_id, f"没有{title}。\n用法 <code>{h(usage)}</code>")
                return
            lines = [f"<b>{h(title)}</b>"]
            lines.extend(f"• <code>{h(mid)}</code>" for mid in current)
            self._reply(chat_id, "\n".join(lines))
            return
        for mid in ids:
            if mid not in current:
                current.append(mid)
        self._write_settings({key: current})
        text = f"已加入{title} " + " ".join(f"<code>{h(mid)}</code>" for mid in ids)
        if tail:
            text += "\n" + tail
        self._reply(chat_id, text)

    def _cmd_id_unlist(self, chat_id: int, arg: str, *, key: str, usage: str) -> None:
        ids = [p for p in arg.split() if p.isdigit()]
        if not ids:
            self._reply(chat_id, f"用法 <code>{h(usage)}</code>")
            return
        current = [mid for mid in (self._saved().get(key) or []) if mid not in ids]
        self._write_settings({key: current})
        self._quiet(ids)
        self._reply(chat_id, "已取消 " + " ".join(f"<code>{h(mid)}</code>" for mid in ids))

    def _cmd_stars(self, chat_id: int, arg: str) -> None:
        raw = arg.strip()
        if not raw.isdigit():
            self._reply(chat_id, f"用法 <code>/stars 0-5</code>\n当前 {self._cfg().min_stars}")
            return
        n = max(0, min(5, int(raw)))
        self._write_settings({"min_stars": n})
        self._reply(chat_id, f"比赛提醒最低星级 <b>{n}</b>")

    def _cmd_silent(self, chat_id: int, arg: str) -> None:
        raw = arg.strip().lower()
        if raw in {"0", "off", "false", "no", "关", "关闭"}:
            self._write_settings({"silent": False})
            self._reply(chat_id, "通知会响铃")
            return
        if raw in {"", "1", "on", "true", "yes", "开", "开启"}:
            self._write_settings({"silent": True})
            self._reply(chat_id, "通知无声")
            return
        self._reply(chat_id, "用法 <code>/silent</code> 或 <code>/silent off</code>")

    def _cmd_ignore(self, chat_id: int, arg: str) -> None:
        ids = [p for p in arg.split() if p.isdigit()]
        current = list(self._saved().get("ignored") or [])
        if not ids:
            if not current:
                self._reply(chat_id, "没有忽略的比赛。\n用法 <code>/ignore 比赛id</code>")
                return
            lines = ["<b>已忽略</b>"]
            lines.extend(f"• <code>{h(mid)}</code>" for mid in current)
            self._reply(chat_id, "\n".join(lines))
            return
        for mid in ids:
            if mid not in current:
                current.append(mid)
        self._write_settings({"ignored": current})
        self._kick()
        self._reply(chat_id, "已忽略 " + " ".join(f"<code>{h(mid)}</code>" for mid in ids))

    def _cmd_unignore(self, chat_id: int, arg: str) -> None:
        ids = [p for p in arg.split() if p.isdigit()]
        if not ids:
            self._reply(chat_id, "用法 <code>/unignore 比赛id</code>")
            return
        current = [mid for mid in (self._saved().get("ignored") or []) if mid not in ids]
        self._write_settings({"ignored": current})
        self._quiet(ids)
        self._kick()
        self._reply(chat_id, "已恢复 " + " ".join(f"<code>{h(mid)}</code>" for mid in ids) + "\n下一次比分变化才会推")

    def _cmd_stop_watch(self, chat_id: int) -> None:
        self._write_score_chats(chat_id, multi=False, single=False)
        self._kick()
        self._reply(
            chat_id,
            "本群比分已关。\n多场 <code>/watch</code>\n单场 <code>/follow on</code>\n赛事提醒用 <code>/track</code>",
        )

    def _cmd_watch(self, chat_id: int, arg: str) -> None:
        raw = arg.strip().lower()
        if raw in {"0", "off", "false", "no", "关", "关闭"}:
            self._write_score_chats(chat_id, multi=False)
            self._kick()
            self._reply(chat_id, "本群多场比分已关。单场还开着的话，用 <code>/follow off</code>。")
            return
        self._write_score_chats(chat_id, multi=True)
        self._quiet(all_matches=True)
        self._kick()
        ignored = self._saved().get("ignored") or []
        extra = ""
        if ignored:
            extra = "\n仍忽略 " + " ".join(f"<code>{h(mid)}</code>" for mid in ignored)
        self._reply(
            chat_id,
            "本群已打开多场比分。Major/T1，以及 <code>/cover</code> 的赛事，只推到这个群。"
            + extra
            + "\n不补发当前比分。",
        )

    def _cmd_track(self, chat_id: int) -> None:
        self._write_settings({"event_watch": True})
        self._kick()
        self._reply(chat_id, "赛程和赛事倒计时已开。错过的那一次不补发。")

    def _cmd_untrack(self, chat_id: int) -> None:
        self._write_settings({"event_watch": False})
        self._kick()
        self._reply(chat_id, "赛程和赛事倒计时已关。比赛比分不受影响。\n恢复发 <code>/track</code>")

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
        self._reply(chat_id, ("已加入" if added else "已在名单里") + f" <code>{gid}</code> {title}".rstrip())

    def _cmd_deny(self, chat_id: int, arg: str) -> None:
        target = arg.strip()
        gid = int(target) if target.lstrip("-").isdigit() else int(chat_id)
        if remove_group(gid):
            self._reply(chat_id, f"已移除 <code>{gid}</code>")
            return
        self._reply(chat_id, f"名单里没有 <code>{gid}</code>")

    def _cmd_groups(self, chat_id: int) -> None:
        rows = list_groups()
        if not rows:
            self._reply(chat_id, "还没有通知群。把 bot 拉进群后发 /allow")
            return
        lines = ["<b>通知群</b>"]
        for g in rows:
            lines.append(f"• <code>{h(g.get('id'))}</code> {h(g.get('title') or '')}".rstrip())
        self._reply(chat_id, "\n".join(lines))

    def _cmd_status(self, chat_id: int) -> None:
        cfg = self._cfg()
        with self._state_lock:
            tracked = len(self._state.get("matches") or {})
            seeded = bool(self._state.get("matches_seeded"))
        when = ""
        if self.last_poll_at:
            when = datetime.fromtimestamp(self.last_poll_at, CST).strftime("%m-%d %H:%M:%S")
        lines = [
            "<b>Status</b>",
            "时区 <code>UTC+8</code>",
            f"通知群 <b>{len(group_ids())}</b>  管理员私聊 <b>{len(self.admin_ids)}</b>",
            f"无声 <b>{'yes' if self._silent() else 'no'}</b>",
            f"比赛星级 ≥ <b>{cfg.min_stars}</b> 且 Major/T1",
            f"多场比分群 <b>{len(cfg.score_multi)}</b>  单场比分群 <b>{len(cfg.score_single)}</b>",
            f"赛程提醒 <b>{'on' if cfg.event_watch else 'off'}</b>  <code>{cfg.digest_morning:02d}:00</code> <code>{cfg.digest_evening:02d}:00</code>",
            f"赛事倒计时 <b>{'on' if cfg.event_watch else 'off'}</b>  前 <code>{cfg.event_days}</code> 天 / <code>{cfg.event_hours}</code> 小时",
            f"单场 <b>{len(cfg.followed)}</b>  赛事 <b>{len(cfg.covered)}</b>",
            f"忽略 <b>{len(cfg.ignored)}</b>",
            f"cf_clearance <b>{'yes' if self.session.has_clearance() else 'no'}</b>",
            "抓取 <code>curl</code>",
            f"已跟踪比赛 <b>{tracked}</b> seeded=<code>{seeded}</code>",
            f"上次轮询 <code>{h(when or '-')}</code>",
        ]
        if self.last_error:
            lines.append(f"最近错误 <code>{h(self.last_error[:180])}</code>")
        self._reply(chat_id, "\n".join(lines))

    def _cmd_debug(
        self,
        chat_id: int,
        *,
        user_id: int | None,
        chat_title: str,
        chat_type: str,
    ) -> None:
        self._reply(
            chat_id,
            "\n".join(
                [
                    "<b>debug</b>",
                    f"user <code>{h(user_id)}</code>",
                    f"chat <code>{h(chat_id)}</code> {h(chat_type)} {h(chat_title)}",
                    f"admin <code>{self.is_admin(user_id)}</code>",
                    f"listed <code>{int(chat_id) in group_ids()}</code>",
                ]
            ),
        )

    def _cmd_cookie(self, chat_id: int, arg: str, *, message_id: int | None) -> None:
        if arg.strip():
            self._apply_cookie(chat_id, arg, message_id=message_id)
            return
        self._await_cookie.add(chat_id)
        self._reply(chat_id, "把 Cookie 整行或 session.json 贴过来。取消发 /status。")

    def _apply_cookie(self, chat_id: int, raw: str, *, message_id: int | None) -> None:
        self._await_cookie.discard(chat_id)
        if not self.session.path:
            self.session.path = Path(os.environ.get("HLTV_SESSION") or "data/session.json")
        self.session.apply_paste(raw)
        names = self.session.cookie_names()
        if not names:
            self._reply(chat_id, "Cookie 是空的，没写入有效内容")
            return
        if message_id is not None:
            self.tg.delete_message(chat_id, message_id)
        self._reply(
            chat_id,
            "Cookie 已更新\n"
            f"cf_clearance: {'yes' if self.session.has_clearance() else 'NO（请贴完整头）'}\n"
            f"names: {', '.join(names)}",
        )

    def handle_added_to_chat(self, upd: dict) -> None:
        member = upd.get("my_chat_member") or {}
        chat = member.get("chat") or {}
        new = (member.get("new_chat_member") or {}).get("status") or ""
        old = (member.get("old_chat_member") or {}).get("status") or ""
        cid = chat.get("id")
        if new not in ("member", "administrator") or old in ("member", "administrator") or cid is None:
            return
        from_id = (member.get("from") or {}).get("id")
        if self.can_setup_chat(int(cid), from_id, chat.get("type") or ""):
            self._reply(int(cid), f"<b>已进群</b>\n<b>{h(chat.get('title') or '')}</b>\n发 /allow 加入通知")

    def _schedule_delete(self, chat_id: int, message_id: int) -> None:
        delay = float(self.msg_ttl or 0)
        if delay <= 0 or not message_id:
            return

        def _run() -> None:
            try:
                self.tg.delete_message(chat_id, message_id)
            except Exception:
                log.debug("delete_message chat=%s msg=%s failed", chat_id, message_id)

        threading.Timer(delay, _run).start()

    def _reply_card(self, chat_id: int, card: dict, caption: str, fallback: str, *, keep: bool = False) -> None:
        try:
            from hltv_bot.cards import render_card

            png = render_card(card)
        except Exception:
            log.exception("card render")
            self._reply(chat_id, fallback, keep=keep)
            return
        msg = self.tg.send_photo(chat_id, png, caption=caption, filename="hltv.png")
        mid = msg.get("message_id") if isinstance(msg, dict) else None
        if mid is not None and not keep:
            self._schedule_delete(chat_id, int(mid))

    def _reply(self, chat_id: int, text: str, *, keep: bool = False) -> dict:
        msg = self.tg.send_message(chat_id, text)
        mid = msg.get("message_id") if isinstance(msg, dict) else None
        if mid is not None and not keep:
            self._schedule_delete(chat_id, int(mid))
        return msg

    def _notify_admins(self, text: str) -> None:
        for aid in sorted(self.admin_ids):
            try:
                self.tg.send_message(aid, text)
            except Exception:
                log.exception("notify admin %s", aid)

    def _notify_admins_photo(self, photo_bytes: bytes, *, caption: str, filename: str = "cf-challenge.png") -> None:
        for aid in sorted(self.admin_ids):
            try:
                self.tg.send_photo(aid, photo_bytes, caption=caption[:1024], filename=filename)
            except Exception:
                log.exception("notify admin photo %s", aid)

    def _score_recipients(self, lane: str) -> list[int]:
        cfg = self._cfg()
        ids: set[int] = set()
        if lane in {"single", "both"}:
            ids.update(int(item) for item in cfg.score_single)
        if lane in {"multi", "both"}:
            ids.update(int(item) for item in cfg.score_multi)
        return sorted(ids)

    def _broadcast_score(self, note) -> None:
        """One live card per match. The new photo replaces the previous one."""
        ids = self._score_recipients(getattr(note, "lane", "") or "")
        caption = note.html if hasattr(note, "html") else str(note)
        if not ids:
            log.info("score skipped, no opted-in chat: %s", caption.replace("\n", " ")[:120])
            return
        silent = self._silent()
        png = None
        card = getattr(note, "card", None)
        if card:
            try:
                from hltv_bot.cards import render_card

                png = render_card(card)
            except Exception:
                log.exception("card render")
        mid = str(getattr(note, "match_id", "") or "")
        with self._state_lock:
            book = dict(self._state.get("score_msgs") or {})
            slot = dict(book.get(mid) or {})
        for gid in ids:
            previous = slot.get(str(gid))
            try:
                if png:
                    msg = self.tg.send_photo(gid, png, caption=caption, filename="hltv.png", silent=silent)
                else:
                    msg = self.tg.send_message(gid, caption, silent=silent)
            except Exception:
                log.exception("score chat=%s", gid)
                continue
            message_id = msg.get("message_id") if isinstance(msg, dict) else None
            if message_id is None:
                continue
            slot[str(gid)] = int(message_id)
            if previous and int(previous) != int(message_id):
                try:
                    self.tg.delete_message(gid, int(previous))
                except Exception:
                    log.debug("score delete chat=%s msg=%s failed", gid, previous)
        if mid:
            with self._state_lock:
                book = dict(self._state.get("score_msgs") or {})
                book[mid] = slot
                self._state["score_msgs"] = book
                _save_state(self._state, self.state_path)

    def _broadcast(self, note) -> None:
        if str(getattr(note, "match_id", "") or ""):
            self._broadcast_score(note)
            return
        silent = self._silent()
        ids = set(group_ids())
        ids.update(int(aid) for aid in self.admin_ids)
        ordered = sorted(ids)
        caption = note.html if hasattr(note, "html") else str(note)
        if not ordered:
            log.info("remind skipped, no recipients: %s", caption.replace("\n", " ")[:120])
            return
        png = None
        card = getattr(note, "card", None)
        if card:
            try:
                from hltv_bot.cards import render_card

                png = render_card(card)
            except Exception:
                log.exception("card render")
        for gid in ordered:
            try:
                if png:
                    self.tg.send_photo(gid, png, caption=caption, filename="hltv.png", silent=silent)
                else:
                    self.tg.send_message(gid, caption, silent=silent)
            except Exception:
                log.exception("remind chat=%s", gid)

    def _note_cf(self, where: str, err: Exception) -> None:
        self.last_error = f"{where}: {err}"
        now = time.monotonic()
        if self._cf_alerted_at and now - self._cf_alerted_at < CF_ALERT_EVERY:
            return
        self._cf_alerted_at = now
        self._notify_admins(f"<b>HLTV Cookie 失效</b>\n{h(where)}\n发 /cookie 更新")

    def _maybe_events(self) -> None:
        now = time.monotonic()
        if self._event_rows is not None and now < self._events_next:
            return
        if now < self._events_retry_at:
            return
        try:
            self._event_rows = fetch_events(self.session)
        except CloudflareError as e:
            self._note_cf("events", e)
            self._events_retry_at = now + 300
            return
        except Exception as e:
            self.last_error = f"events: {e}"
            log.exception("fetch events")
            self._events_retry_at = now + 300
            return
        self._events_next = now + EVENTS_CACHE_TTL
        log.info("events refreshed n=%s", len(self._event_rows or []))

    def _refresh_list(self) -> None:
        try:
            self._list_rows = fetch_matches(self.session, fresh=True)
        except CloudflareError as e:
            self._note_cf("matches", e)
            return
        except Exception as e:
            self.last_error = f"matches: {e}"
            log.exception("fetch matches")
            return
        self._list_at = time.monotonic()

    def _plan(self) -> None:
        if self._list_at <= 0:
            return
        with self._state_lock:
            state, notes = plan_reminders(
                self._state,
                self._list_rows,
                self._event_rows,
                now=datetime.now(CST),
                cfg=self._cfg(),
            )
            self._state = state
            _save_state(state, self.state_path)
        self.last_poll_at = time.time()
        self.last_error = ""
        for note in notes:
            log.info("remind %s", note.key)
            self._broadcast(note)

    def tick_reminders(self) -> float:
        """Fetch only what is due. Return seconds until the next matches fetch."""
        self._maybe_events()
        now_m = time.monotonic()
        if self._list_at <= 0 or now_m >= self._list_next:
            self._refresh_list()
            if self._list_at <= 0:
                self._list_next = now_m + 300
                return 300
            self._plan()
        with self._state_lock:
            digests = dict(self._state.get("digests") or {})
        wait = choose_poll_wait(
            self._list_rows,
            self._cfg(),
            datetime.now(CST),
            digests,
            self._event_rows,
        )
        if wait <= 0:
            wait = random.uniform(MATCH_PAGE_MIN, MATCH_PAGE_MAX)
        self._list_next = time.monotonic() + wait
        return wait

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            try:
                wait = self.tick_reminders()
            except Exception:
                log.exception("remind tick")
                wait = 300
            log.info("next poll in %.0fs", wait)
            self._wake.wait(wait)
            self._wake.clear()

    def register_commands(self) -> None:
        for scope in command_scope_clears(self.admin_ids, group_ids()):
            try:
                self.tg.delete_my_commands(scope)
            except Exception:
                log.exception("deleteMyCommands scope=%s", scope.get("type"))
            time.sleep(TG_COMMANDS_GAP)
        for i, (cmds, scope) in enumerate(command_jobs(self.admin_ids, group_ids())):
            if i:
                time.sleep(TG_COMMANDS_GAP)
            self.tg.set_my_commands(cmds, scope)

    def run(self) -> None:
        log.info("bot start admins=%s groups=%s http=curl", sorted(self.admin_ids), sorted(group_ids()))
        threading.Thread(target=self._poll_loop, daemon=True, name="hltv-remind").start()
        try:
            self.register_commands()
        except Exception:
            log.exception("setMyCommands failed")
        offset = 0
        while not self._stop.is_set():
            try:
                updates = self.tg.get_updates(offset=offset, timeout=25)
            except Exception:
                log.exception("getUpdates failed")
                time.sleep(GET_UPDATES_FAIL_SLEEP)
                continue
            for upd in updates:
                offset = int(upd["update_id"]) + 1
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
                        self._reply(int(cid), f"错误: {e}")
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
    os.environ.setdefault("HLTV_HTTP", "curl")
    os.environ.setdefault("HLTV_SCOREBOT", "off")
    return HltvTelegramBot(
        Telegram(token),
        load_session(session_path),
        admin_ids=admin_ids,
        cdp_url=None,
    )
