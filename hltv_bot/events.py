from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Sequence

from hltv_bot.http import request
from hltv_bot.render import classify_event_tier
from hltv_bot.session import BrowserSession

log = logging.getLogger("hltv_bot.events")

EVENTS_URL = "https://www.hltv.org/events"
_EVENTS_CACHE: dict = {"at": 0.0, "rows": []}
EVENTS_CACHE_TTL = 300.0  # 5 minutes cache
CST = timezone(timedelta(hours=8))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def parse_events_list(html: str) -> list[dict]:
    """Parse events from https://www.hltv.org/events page HTML."""
    events: list[dict] = []

    # 1. Ongoing events
    ongoing_holder = re.search(
        r'class="ongoing-events-holder"[\s\S]*?(?=<div class="events-holder"|<div class="big-events"|$)',
        html,
    )
    if ongoing_holder:
        for m in re.finditer(
            r'<a href="(/events/(\d+)/[^\"]+)"[^>]*class="[^\"]*ongoing-event[^\"]*"[^>]*>([\s\S]*?)</a>',
            ongoing_holder.group(0),
        ):
            href, eid, content = m.group(1), m.group(2), m.group(3)
            name_m = re.search(r'class="text-ellipsis">([^<]+)', content)
            name = _clean(name_m.group(1)) if name_m else ""
            dates = re.findall(r'data-unix="(\d+)"', content)
            start_ts = int(dates[0]) // 1000 if dates else 0
            end_ts = int(dates[1]) // 1000 if len(dates) > 1 else start_ts
            events.append(
                {
                    "id": eid,
                    "url": "https://www.hltv.org" + href,
                    "name": name,
                    "live": True,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "location": "",
                    "prize": "",
                }
            )

    # 2. Big events
    for m in re.finditer(
        r'<a href="(/events/(\d+)/[^\"]+)"[^>]*class="[^\"]*big-event[^\"]*"[^>]*>([\s\S]*?)</a>',
        html,
    ):
        href, eid, content = m.group(1), m.group(2), m.group(3)
        name_m = re.search(r'class="big-event-name">([^<]+)', content)
        name = _clean(name_m.group(1)) if name_m else ""
        loc_m = re.search(r'class="big-event-location">([^<]+)', content)
        loc = _clean(loc_m.group(1)) if loc_m else ""
        prize_m = re.search(r'class="col-value"[^>]*title="([^\"]+)"', content)
        prize = _clean(prize_m.group(1)) if prize_m else ""
        dates = re.findall(r'data-unix="(\d+)"', content)
        start_ts = int(dates[0]) // 1000 if dates else 0
        end_ts = int(dates[1]) // 1000 if len(dates) > 1 else start_ts
        events.append(
            {
                "id": eid,
                "url": "https://www.hltv.org" + href,
                "name": name,
                "live": False,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "location": loc,
                "prize": prize,
            }
        )

    # 3. Small events in upcoming months
    months_holder = re.findall(
        r'<div class="events-month">([\s\S]*?)(?=<div class="events-month">|$)',
        html,
    )
    for mh in months_holder:
        for m in re.finditer(
            r'<a href="(/events/(\d+)/[^\"]+)"[^>]*class="[^\"]*small-event[^\"]*"[^>]*>([\s\S]*?)</a>',
            mh,
        ):
            href, eid, content = m.group(1), m.group(2), m.group(3)
            name_m = re.search(r'class="text-ellipsis">([^<]+)', content)
            name = _clean(name_m.group(1)) if name_m else ""
            dates = re.findall(r'data-unix="(\d+)"', content)
            start_ts = int(dates[0]) // 1000 if dates else 0
            end_ts = int(dates[1]) // 1000 if len(dates) > 1 else start_ts
            events.append(
                {
                    "id": eid,
                    "url": "https://www.hltv.org" + href,
                    "name": name,
                    "live": False,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "location": "",
                    "prize": "",
                }
            )

    # Deduplicate by event id
    seen: set[str] = set()
    unique: list[dict] = []
    for ev in events:
        if ev["id"] not in seen:
            seen.add(ev["id"])
            unique.append(ev)

    return unique


def classify_tier(name: str) -> str:
    """Return 'Major', 'T1', 'T2', 'T3', or 'Other'."""
    lower = (name or "").lower()
    if "major" in lower:
        return "Major"
    return classify_event_tier(name, stars=0)


def filter_and_sort_events(
    events: Sequence[dict],
    *,
    allowed_tiers: Sequence[str] = ("Major", "T1"),
    now: datetime | None = None,
) -> list[dict]:
    """Filter events by tier and sort by (live first, then days left ascending, then start_ts)."""
    if now is None:
        now = datetime.now(CST)
    today = now.date()

    filtered: list[dict] = []
    for raw in events:
        ev = dict(raw)
        tier = classify_tier(ev.get("name") or "")
        if tier not in allowed_tiers:
            continue
        ev["tier"] = tier

        start_ts = ev.get("start_ts") or 0
        if start_ts:
            start_dt = datetime.fromtimestamp(start_ts, CST)
            ev["start_date"] = start_dt.date()
            ev["days_left"] = (start_dt.date() - today).days
        else:
            ev["start_date"] = None
            ev["days_left"] = 9999

        filtered.append(ev)

    # Sort: ongoing/live first (0 if live else 1), then days_left ascending, then start_ts
    filtered.sort(
        key=lambda x: (
            0 if x.get("live") else 1,
            x.get("days_left", 9999),
            x.get("start_ts", 0),
        )
    )
    return filtered


def format_events_html(events: Sequence[dict], *, limit: int = 15) -> str:
    """Format events list into Telegram HTML message."""
    if not events:
        return "暂无近期 Major / T1 赛事信息。"

    lines = ["<b>🏆 近期赛事 (Major / T1)</b>\n"]
    for ev in events[:limit]:
        tier = ev.get("tier") or "T2"
        badge = "👑 [Major]" if tier == "Major" else ("🥇 [T1]" if tier == "T1" else "🥈 [T2]")
        name = ev.get("name") or "Unknown Event"

        start_ts = ev.get("start_ts") or 0
        end_ts = ev.get("end_ts") or 0
        if start_ts:
            start_dt = datetime.fromtimestamp(start_ts, CST)
            start_str = start_dt.strftime("%Y-%m-%d")
            if end_ts and end_ts != start_ts:
                end_dt = datetime.fromtimestamp(end_ts, CST)
                end_fmt = "%m-%d" if end_dt.year == start_dt.year else "%Y-%m-%d"
                date_range = start_str + " ~ " + end_dt.strftime(end_fmt)
            else:
                date_range = start_str
        else:
            date_range = "待定"

        days_left = ev.get("days_left", 9999)
        if ev.get("live"):
            status_str = "🔴 <b>进行中 (LIVE)</b>"
        elif days_left > 0:
            status_str = f"⏳ <b>还有 {days_left} 天开赛</b>"
        elif days_left == 0:
            status_str = "⏳ <b>今天开赛</b>"
        else:
            status_str = f"⏳ <b>进行中 (第 {-days_left + 1} 天)</b>"

        meta_parts = [f"📅 {date_range}"]
        loc = ev.get("location")
        if loc:
            meta_parts.append(f"📍 {loc}")
        prize = ev.get("prize")
        if prize and prize not in ("_", "TBA", "Other"):
            meta_parts.append(f"💰 {prize}")
        meta_str = " · ".join(meta_parts)

        lines.append(f"{badge} <b>{name}</b>\n   {status_str}\n   {meta_str}\n")

    return "\n".join(lines).strip()


def fetch_events(sess: BrowserSession, timeout: float = 25.0) -> list[dict]:
    import time as _time

    now = _time.monotonic()
    if _EVENTS_CACHE["rows"] and now - _EVENTS_CACHE["at"] < EVENTS_CACHE_TTL:
        log.debug("events cache hit n=%s age=%.1fs", len(_EVENTS_CACHE["rows"]), now - _EVENTS_CACHE["at"])
        return list(_EVENTS_CACHE["rows"])

    _st, body, _ = request(
        sess,
        "GET",
        EVENTS_URL,
        timeout=timeout,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
        },
    )
    rows = parse_events_list(body.decode("utf-8", "replace"))
    log.info("events fetched n=%s bytes=%s", len(rows), len(body))
    _EVENTS_CACHE["at"] = now
    _EVENTS_CACHE["rows"] = rows
    return list(rows)
