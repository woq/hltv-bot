from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape, unescape
from pathlib import Path
from typing import Sequence

from hltv_bot.http import request
from hltv_bot.session import BrowserSession

log = logging.getLogger("hltv_bot.events")

EVENTS_URL = "https://www.hltv.org/events"
_EVENTS_CACHE: dict = {"at": 0.0, "rows": []}
EVENTS_CACHE_TTL = 24 * 3600.0
CST = timezone(timedelta(hours=8))


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


def country_code_to_emoji(cc: str) -> str:
    """Convert country/region code to Flag emoji."""
    if not cc:
        return ""
    cc_u = cc.upper().strip()
    if len(cc_u) == 2 and all("A" <= c <= "Z" for c in cc_u):
        return chr(ord("🇦") + ord(cc_u[0]) - ord("A")) + chr(ord("🇦") + ord(cc_u[1]) - ord("A"))
    if cc_u in ("EU", "EUROPE"):
        return "🇪🇺"
    if cc_u in ("WORLD", "INT"):
        return "🌐"
    if cc_u in ("NAM", "SAM"):
        return "🌎"
    if cc_u in ("ASIA", "OCE"):
        return "🌏"
    return ""


def format_event_date_range(
    start_ts: int | float | None,
    end_ts: int | float | None = 0,
    *,
    pending: str = "TBD",
    now: datetime | None = None,
) -> str:
    """Date span. Year is omitted only when the whole span is in the current year."""
    try:
        start_n = int(start_ts or 0)
    except (TypeError, ValueError):
        start_n = 0
    if start_n <= 0:
        return pending
    try:
        end_n = int(end_ts or 0)
    except (TypeError, ValueError):
        end_n = 0
    start_dt = datetime.fromtimestamp(start_n, CST)
    end_dt = None
    if end_n > 0 and end_n != start_n:
        end_dt = datetime.fromtimestamp(end_n, CST)
        if end_dt.date() == start_dt.date():
            end_dt = None
    current = (now or datetime.now(CST)).year
    show_year = start_dt.year != current or bool(end_dt and end_dt.year != current)
    fmt = "%Y-%m-%d" if show_year else "%m-%d"
    if end_dt:
        return start_dt.strftime(fmt) + " ~ " + end_dt.strftime(fmt)
    return start_dt.strftime(fmt)


def clean_event_display_name(name: str) -> str:
    """Shorten event name cleanly: Season -> S, remove redundant year."""
    s = (name or "").strip()
    s = re.sub(r"\bSeason\s+(\d+)\b", r"S\1", s, flags=re.I)
    s = re.sub(r"\s+202[4-9]\b", "", s)
    return s.strip()


_FLAGS_CACHE_DIR = Path("data/flags")
_FLAG_URL = "https://www.hltv.org/img/static/flags/30x20/{cc}.gif"


def _stem(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", raw or "")[:40]


def get_flag_img_html(cc: str, sess: BrowserSession | None = None) -> str:
    """Return an HTML <img> for a cached flag. Downloads happen in ensure_flags."""
    del sess
    stem = _stem((cc or "").strip().upper())
    if not stem:
        return ""
    from hltv_bot.team_logos import data_uri_for, find_cached_stem

    path = find_cached_stem(_FLAGS_CACHE_DIR, stem)
    if path is None:
        return ""
    uri = data_uri_for(path)
    if not uri:
        return ""
    return f'<img class="flag-img" src="{uri}" alt="" />'


def ensure_flags(codes: list[str]) -> None:
    """Download missing flag images. Flags stay on disk; the set is small."""
    from hltv_bot.team_logos import download_images, find_cached_stem, save_image

    pending: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in codes:
        stem = _stem((raw or "").strip().upper())
        if not stem or stem in seen:
            continue
        seen.add(stem)
        path = find_cached_stem(_FLAGS_CACHE_DIR, stem)
        if path is not None:
            try:
                path.touch()
            except OSError:
                pass
            continue
        pending.append((stem, _FLAG_URL.format(cc=stem)))
    if not pending:
        return
    fetched = download_images([url for _, url in pending])
    for stem, url in pending:
        data = fetched.get(url)
        if not data:
            continue
        save_image(_FLAGS_CACHE_DIR, stem, data)


def format_location(loc: str, cc: str = "", sess: BrowserSession | None = None) -> str:
    """Format location with flag image and clean city name."""
    flag_html = get_flag_img_html(cc, sess=sess)
    city = (loc or "").strip()
    if "," in city:
        city = city.split(",")[0].strip()
    city = city.rstrip("|").strip()
    if city in ("-", "_", "TBA", "TBD"):
        city = ""

    if flag_html and city:
        return f"{flag_html}<span>{city}</span>"
    if flag_html:
        return flag_html
    return city or "-"


_LOGO_CACHE_DIR = Path("data/event_logos")


def get_cached_logo_data_uri(event_id: str, logo_url: str = "") -> str:
    """Return data URI for a cached event logo. Touches the file so prune keeps it."""
    del logo_url
    stem = _stem(str(event_id or ""))
    if not stem:
        return ""
    from hltv_bot.team_logos import data_uri_for, find_cached_stem

    path = find_cached_stem(_LOGO_CACHE_DIR, stem)
    if path is None:
        return ""
    return data_uri_for(path)


def ensure_event_logos(pairs: list[tuple[str, str]]) -> None:
    """Download event logos shown on the next card. Drops files unused for 7 days."""
    from hltv_bot.team_logos import EVENT_LOGO_MAX_AGE_SEC, download_images, find_cached_stem, prune_image_dir, save_image

    prune_image_dir(_LOGO_CACHE_DIR, EVENT_LOGO_MAX_AGE_SEC)
    pending: list[tuple[str, str]] = []
    seen: set[str] = set()
    for event_id, logo_url in pairs:
        stem = _stem(str(event_id or ""))
        url = unescape((logo_url or "").strip())
        if not stem or not url or stem in seen:
            continue
        seen.add(stem)
        path = find_cached_stem(_LOGO_CACHE_DIR, stem)
        if path is not None:
            try:
                path.touch()
            except OSError:
                pass
            continue
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = "https://www.hltv.org" + url
        pending.append((stem, url))
    if not pending:
        return
    fetched = download_images([url for _, url in pending])
    for stem, url in pending:
        data = fetched.get(url)
        if data:
            save_image(_LOGO_CACHE_DIR, stem, data)


def cache_event_logo(event_id: str, logo_url: str, sess: BrowserSession | None = None) -> str:
    """Fetch one event logo into the cache. Returns a data URI or empty string."""
    del sess
    ensure_event_logos([(event_id, logo_url)])
    return get_cached_logo_data_uri(event_id)


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

            logo_m = re.search(r'<img[^>]+src="([^"]+)"', content)
            logo_url = unescape(logo_m.group(1)) if logo_m else ""

            flag_m = re.search(r'/img/static/flags/30x20/([A-Za-z0-9_]+)\.gif', content)
            cc = flag_m.group(1) if flag_m else ""
            loc_m = re.search(r'class="(?:big-event-location|smallCountry|location)[^"]*">([\s\S]*?)</span>', content)
            loc = _clean(re.sub(r'<[^>]+>', '', loc_m.group(1))) if loc_m else ""

            events.append(
                {
                    "id": eid,
                    "url": "https://www.hltv.org" + href,
                    "name": name,
                    "live": True,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "location": loc,
                    "country_code": cc,
                    "logo_url": logo_url,
                    "prize": "",
                }
            )

    # 2. Big events
    for m in re.finditer(
        r'<a href="(/events/(\d+)/[^\"]+)"[^>]*class="[^\"]*\bbig-event\b[^\"]*"[^>]*>([\s\S]*?)</a>',
        html,
    ):
        href, eid, content = m.group(1), m.group(2), m.group(3)
        name_m = re.search(r'class="big-event-name">([^<]+)', content)
        name = _clean(name_m.group(1)) if name_m else ""
        loc_m = re.search(r'class="big-event-location">([^<]+)', content)
        loc = _clean(loc_m.group(1)) if loc_m else ""
        flag_m = re.search(r'/img/static/flags/30x20/([A-Za-z0-9_]+)\.gif', content)
        cc = flag_m.group(1) if flag_m else ""
        prize_m = re.search(r'class="col-value"[^>]*title="([^\"]+)"', content)
        prize = _clean(prize_m.group(1)) if prize_m else ""
        dates = re.findall(r'data-unix="(\d+)"', content)
        start_ts = int(dates[0]) // 1000 if dates else 0
        end_ts = int(dates[1]) // 1000 if len(dates) > 1 else start_ts

        logo_m = re.search(r'<img[^>]+src="([^"]+)"', content)
        logo_url = unescape(logo_m.group(1)) if logo_m else ""

        events.append(
            {
                "id": eid,
                "url": "https://www.hltv.org" + href,
                "name": name,
                "live": False,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "location": loc,
                "country_code": cc,
                "logo_url": logo_url,
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
            r'<a href="(/events/(\d+)/[^\"]+)"[^>]*class="[^\"]*\bsmall-event\b[^\"]*"[^>]*>([\s\S]*?)</a>',
            mh,
        ):
            href, eid, content = m.group(1), m.group(2), m.group(3)
            name_m = re.search(r'class="text-ellipsis">([^<]+)', content)
            name = _clean(name_m.group(1)) if name_m else ""
            dates = re.findall(r'data-unix="(\d+)"', content)
            start_ts = int(dates[0]) // 1000 if dates else 0
            end_ts = int(dates[1]) // 1000 if len(dates) > 1 else start_ts

            logo_m = re.search(r'<img[^>]+src="([^"]+)"', content)
            logo_url = unescape(logo_m.group(1)) if logo_m else ""

            flag_m = re.search(r'/img/static/flags/30x20/([A-Za-z0-9_]+)\.gif', content)
            cc = flag_m.group(1) if flag_m else ""
            loc_m = re.search(r'class="smallCountry"[^>]*>([\s\S]*?)</span>', content)
            loc = _clean(re.sub(r'<[^>]+>', '', loc_m.group(1))) if loc_m else ""
            prize_m = re.search(r'class="col-value small-col prizePoolEllipsis"[^>]*title="([^\"]+)"', content)
            prize = _clean(prize_m.group(1)) if prize_m else ""

            events.append(
                {
                    "id": eid,
                    "url": "https://www.hltv.org" + href,
                    "name": name,
                    "live": False,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "location": loc,
                    "country_code": cc,
                    "logo_url": logo_url,
                    "prize": prize,
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


_TIER_KEYWORDS = {
    "T1": [
        "major", "pgl", "iem", "katowice", "cologne",
        "blast", "esl pro league", "epl", "world final",
    ],
    "T2": [
        "cct", "challenger league", "ecl", "res", "yalla",
        "compass", "thunderpick", "mesa", "fiesta", "nodwin", "starladder",
    ],
    "T3": [
        "closed qualifier", "open qualifier", "qualifier",
        "cash cup", "academy", "regional cup", "series qualifier", "esea",
    ],
}


def classify_event_tier(event_name: str, stars: int = 0) -> str:
    """Classify match/event into T1, T2, T3 or Other."""
    ev = (event_name or "").lower()
    if stars >= 4:
        return "T1"

    is_qualifier = bool(re.search(r"\b(qualifier|closed|open\s+qualifier)\b", ev))

    for kw in _TIER_KEYWORDS["T1"]:
        if kw in ev:
            if is_qualifier:
                return "T2" if stars >= 1 else "T3"
            return "T1"

    if stars >= 2:
        return "T2"

    for kw in _TIER_KEYWORDS["T2"]:
        if kw in ev:
            if is_qualifier:
                return "T3"
            return "T2"

    for kw in _TIER_KEYWORDS["T3"]:
        if kw in ev:
            return "T3"

    if stars == 1:
        return "T3"

    return "Other"


def tier_rank(tier: str) -> int:
    return {"T1": 1, "T2": 2, "T3": 3, "Other": 4}.get(tier, 5)


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
    max_days: int | None = 92,
    now: datetime | None = None,
) -> list[dict]:
    """Filter events by tier and timeframe (default 3 months) and sort by live first then days left."""
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

        if max_days is not None and not ev.get("live"):
            days_left = ev["days_left"]
            if days_left > max_days:
                continue

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

    lines = ["<b>近期赛事</b>", "<i>Major / T1</i>", ""]
    for ev in events[:limit]:
        tier = ev.get("tier") or "T2"
        badge = "Major" if tier == "Major" else tier
        name = escape(ev.get("name") or "Unknown Event")
        date_range = format_event_date_range(ev.get("start_ts") or 0, ev.get("end_ts") or 0, pending="待定")
        days_left = ev.get("days_left", 9999)
        if ev.get("live"):
            status_str = "进行中"
        elif days_left > 0:
            status_str = f"还有 {days_left} 天开赛"
        elif days_left == 0:
            status_str = "今天开赛"
        else:
            status_str = f"进行中 · 第 {-days_left + 1} 天"
        loc = (ev.get("location") or "").strip()
        flag = country_code_to_emoji(str(ev.get("country_code") or ""))
        place = " ".join(bit for bit in (flag, loc) if bit)
        prize = ev.get("prize")
        quote = [f"<b>{name}</b>", badge]
        if place:
            quote.append(place)
        quote.append(date_range)
        quote.append(f"<b>{status_str}</b>")
        if prize and prize not in ("_", "TBA", "Other"):
            quote.append(prize)
        url = (ev.get("url") or "").strip()
        if url:
            quote.append(f'<a href="{escape(url)}">打开赛事</a>')
        lines.append("<blockquote>" + "\n".join(quote) + "</blockquote>")
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
    html_text = body.decode("utf-8", "replace")
    rows = parse_events_list(html_text)

    # Enrich event logos with true icons from homepage sidebar if available
    try:
        _st_home, home_body, _ = request(
            sess,
            "GET",
            "https://www.hltv.org/",
            timeout=10.0,
            headers={"accept": "text/html"},
        )
        home_html = home_body.decode("utf-8", "replace")
        aside = re.search(r'<aside><h1><a href="/events"[^>]*>EVENTS</a></h1>([\s\S]*?)</aside>', home_html)
        if aside:
            for m in re.finditer(r'<a href="/events/(\d+)/[^"]*"[^>]*>([\s\S]*?)</a>', aside.group(1)):
                eid, content = m.group(1), m.group(2)
                img_m = re.search(r'<img[^>]+src="([^"]+)"', content)
                if img_m:
                    aside_logo = unescape(img_m.group(1))
                    for r in rows:
                        if r.get("id") == eid and not r.get("logo_url"):
                            r["logo_url"] = aside_logo
    except Exception as e:
        log.debug("failed to enrich logos from homepage aside: %s", e)

    log.info("events fetched n=%s bytes=%s", len(rows), len(body))
    _EVENTS_CACHE["at"] = now
    _EVENTS_CACHE["rows"] = rows
    return list(rows)
