from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from html import unescape

from hltv_bot.http import request
from hltv_bot.session import BrowserSession

log = logging.getLogger("hltv_bot.matches")

MATCHES_URL = "https://www.hltv.org/matches"
_MATCH_CACHE: dict = {"at": 0.0, "rows": []}
MATCH_CACHE_TTL = 45.0
_MATCH_CACHE_TTL = MATCH_CACHE_TTL
MATCH_HREF = re.compile(r'href="(/matches/(\d+)/([^"]+))"')
MATCH_TEAMS_BLOCK = re.compile(r'<a[^>]*class="[^"]*match-teams[^"]*"[^>]*>([\s\S]*?)</a>', re.I)
TEAM_NAME = re.compile(
    r'class="[^"]*(?:match-?teamname|matchTeamName|\bteam\b)[^"]*"[^>]*>(?:<[^>]+>)*\s*([^<]+)',
    re.I,
)
EVENT_ATTR = re.compile(r'data-event-headline="([^"]+)"', re.I)
EVENT_NAME = re.compile(
    r'class="[^"]*match-?event(?:name)?[^"]*"[^>]*>(?:<[^>]+>)*\s*([^<]+)',
    re.I,
)
DATA_STARS = re.compile(r'data-(?:stars|star-rating|rating)="(\d)"', re.I)
DATA_UNIX = re.compile(r'data-unix="(\d{10,13})"')
MATCH_TIME_TEXT = re.compile(r'class="[^"]*(?:matchTime|time)[^"]*"[^>]*>\s*(\d{1,2}:\d{2})\s*<', re.I)
CST = timezone(timedelta(hours=8))


def _abs(href: str) -> str:
    if href.startswith("http"):
        return href
    return "https://www.hltv.org" + href


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(text)).strip()


_ACRONYMS = {
    "g2": "G2",
    "navi": "NaVi",
    "natus": "Natus",
    "vincere": "Vincere",
    "m80": "M80",
    "esl": "ESL",
    "cct": "CCT",
    "iem": "IEM",
    "blast": "BLAST",
    "pgl": "PGL",
    "faze": "FaZe",
    "mouz": "MOUZ",
    "furia": "FURIA",
    "pain": "paiN",
    "mibr": "MIBR",
    "og": "OG",
    "c9": "C9",
    "nip": "NiP",
    "saw": "SAW",
    "ap": "AP",
    "eu": "EU",
    "na": "NA",
    "sa": "SA",
    "asia": "Asia",
    "europe": "Europe",
    "pacific": "Pacific",
    "series": "Series",
    "closed": "Closed",
    "open": "Open",
    "qualifier": "Qualifier",
    "challenger": "Challenger",
    "league": "League",
    "season": "Season",
    "cup": "Cup",
    "academy": "Academy",
    "ex": "ex",
}


def format_start_time(unix_raw: str | int | None, *, live: bool = False) -> str:
    if unix_raw in (None, ""):
        return "LIVE" if live else ""
    try:
        n = int(unix_raw)
    except (TypeError, ValueError):
        return "LIVE" if live else ""
    if n > 10_000_000_000:
        n //= 1000
    dt = datetime.fromtimestamp(n, CST)
    now = datetime.now(CST)
    clock = dt.strftime("%H:%M")
    if dt.date() != now.date():
        return dt.strftime("%m/%d ") + clock
    return clock


def pretty_name(text: str) -> str:
    s = _clean(text)
    if not s:
        return s
    if any(c.isupper() for c in s) and not s.islower():
        return s
    out: list[str] = []
    for w in s.split(" "):
        k = w.lower()
        if k in _ACRONYMS:
            out.append(_ACRONYMS[k])
        elif k.isdigit():
            out.append(w)
        else:
            out.append(w[:1].upper() + w[1:].lower() if w else w)
    return " ".join(out)


def _stars_in(chunk: str) -> int:
    m = DATA_STARS.search(chunk)
    if m:
        return max(0, min(5, int(m.group(1))))
    all_s = len(re.findall(r"fa-star", chunk, re.I))
    empty = len(re.findall(r"fa-star-o|fa-star empty", chunk, re.I))
    n = all_s - empty
    if n <= 0:
        n = len(re.findall(r"★", chunk))
    return max(0, min(5, n))


def _teams_event_from_slug(slug: str) -> tuple[str, str, str]:
    slug = unescape(slug)
    if "-vs-" not in slug:
        pretty = slug.replace("-", " ")
        return "TBD", "TBD", pretty
    left, right = slug.split("-vs-", 1)
    t1 = left.replace("-", " ")
    # event tokens often start at known series names
    parts = right.split("-")
    event_i = None
    keys = {
        "cct",
        "esl",
        "blast",
        "iem",
        "major",
        "pgl",
        "starladder",
        "nodwin",
        "exort",
        "gluck",
        "logitech",
        "kibertochka",
        "fiesta",
        "challenger",
        "qualifier",
    }
    for i, p in enumerate(parts):
        if p.lower() in keys:
            event_i = i
            break
    if event_i is None and len(parts) >= 3:
        event_i = max(1, len(parts) - 4)
    if event_i is None:
        return t1, right.replace("-", " "), ""
    t2 = " ".join(parts[:event_i])
    event = " ".join(parts[event_i:])
    return t1, t2, event


def _chunk_around(html: str, pos: int, span: int = 1800) -> str:
    start = max(0, pos - span)
    end = min(len(html), pos + span)
    return html[start:end]


def parse_match_list(html: str, *, limit: int = 100, exclude_tbd: bool = False) -> list[dict[str, str]]:
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for m in MATCH_HREF.finditer(html):
        href, mid, slug = m.group(1), m.group(2), m.group(3)
        if mid in seen:
            continue
        seen.add(mid)
        # Locate match container boundary instead of broad 3600-char window
        before_pos = html.rfind('<div class="upcomingMatch', 0, m.start())
        live_pos = html.rfind('<div class="liveMatch', 0, m.start())
        c_start = max(before_pos, live_pos)
        if c_start == -1 or (m.start() - c_start > 1500):
            c_start = max(0, m.start() - 400)

        next_up = html.find('<div class="upcomingMatch', m.end())
        next_live = html.find('<div class="liveMatch', m.end())
        candidates_end = [x for x in (next_up, next_live) if x != -1]
        c_end = min(candidates_end) if candidates_end else min(len(html), m.end() + 1000)
        chunk = html[c_start:c_end]

        prefix = html[c_start:m.start()]
        live = "liveMatch" in html[c_start:m.start() + 100] or "matchLive" in html[c_start:m.start() + 100]

        teams: list[str] = []
        mt = MATCH_TEAMS_BLOCK.search(chunk)
        if mt:
            teams = [_clean(x) for x in TEAM_NAME.findall(mt.group(1)) if _clean(x)]
        if len(teams) < 2:
            teams = [_clean(x) for x in TEAM_NAME.findall(chunk) if _clean(x)]

        t1, t2, event = _teams_event_from_slug(slug)
        if len(teams) >= 2:
            t1, t2 = teams[0], teams[1]
        elif len(teams) == 1:
            t1 = teams[0]
            if not t2 or t2 == "TBD":
                t2 = "TBD"

        ev_attr = EVENT_ATTR.search(chunk)
        if ev_attr:
            event = _clean(ev_attr.group(1))
        else:
            ev = EVENT_NAME.search(chunk)
            if ev:
                event = _clean(ev.group(1)) or event
        t1, t2, event = pretty_name(t1), pretty_name(t2), pretty_name(event)
        stars = _stars_in(chunk)
        unix = None
        for um in DATA_UNIX.finditer(prefix):
            unix = um.group(1)
        if unix is None:
            um = DATA_UNIX.search(chunk)
            unix = um.group(1) if um else None
        if unix is None:
            # Look backwards up to 3000 chars for the parent date/time container
            wide_before = html[max(0, m.start() - 3000):m.start()]
            for um in DATA_UNIX.finditer(wide_before):
                unix = um.group(1)

        time_s = format_start_time(unix, live=live)
        if not time_s and not live:
            tm = MATCH_TIME_TEXT.search(chunk)
            if tm:
                time_s = tm.group(1)
        # If both teams are TBD / placeholder, optionally exclude
        _u1, _u2 = t1.strip().upper(), t2.strip().upper()
        if exclude_tbd and (not _u1 or _u1 in ("?", "TBD")) and (not _u2 or _u2 in ("?", "TBD")):
            continue

        rows.append(
            {
                "id": mid,
                "url": _abs(href),
                "team1": t1,
                "team2": t2,
                "event": event,
                "title": f"{t1} vs {t2}".strip() or pretty_name(slug.replace("-", " ")),
                "live": "1" if live else "0",
                "stars": str(stars),
                "time": time_s,
                "unix": str(unix or ""),
            }
        )
        if len(rows) >= limit:
            break

    def _match_sort_key(r: dict) -> tuple:
        live = 0 if r.get("live") == "1" else 1
        t1 = (r.get("team1") or "").strip().upper()
        t2 = (r.get("team2") or "").strip().upper()
        has_tbd = 1 if (not t1 or not t2 or t1 in ("?", "TBD") or t2 in ("?", "TBD")) else 0
        stars = int(r.get("stars") or 0)
        return (live, has_tbd, -stars)

    rows.sort(key=_match_sort_key)
    return rows


def parse_match_meta(html: str, url: str = "") -> dict[str, str | None]:
    def g(rx: re.Pattern[str]) -> str | None:
        m = rx.search(html)
        return unescape(m.group(1)) if m else None

    return {
        "url": url or None,
        "scorebotId": g(re.compile(r'data-scorebot-id="(\d+)"')),
        "scorebotUrl": g(re.compile(r'data-scorebot-url="([^"]+)"')),
        "team1": g(re.compile(r'data-team1-name="([^"]*)"')),
        "team2": g(re.compile(r'data-team2-name="([^"]*)"')),
    }


def fetch_matches(sess: BrowserSession, timeout: float = 20.0) -> list[dict[str, str]]:
    import time as _time

    now = _time.monotonic()
    if _MATCH_CACHE["rows"] and now - _MATCH_CACHE["at"] < _MATCH_CACHE_TTL:
        log.debug("matches cache hit n=%s age=%.1fs", len(_MATCH_CACHE["rows"]), now - _MATCH_CACHE["at"])
        return list(_MATCH_CACHE["rows"])
    _st, body, _ = request(
        sess,
        "GET",
        MATCHES_URL,
        timeout=timeout,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "none",
        },
    )
    rows = parse_match_list(body.decode("utf-8", "replace"))
    live_n = sum(1 for r in rows if r.get("live") == "1")
    log.info("matches fetched n=%s live=%s bytes=%s", len(rows), live_n, len(body))
    _MATCH_CACHE["at"] = now
    _MATCH_CACHE["rows"] = rows
    return list(rows)


def fetch_match_meta(sess: BrowserSession, url: str, timeout: float = 20.0) -> dict[str, str | None]:
    if url.isdigit():
        url = f"https://www.hltv.org/matches/{url}/x"
    _st, body, _ = request(
        sess,
        "GET",
        url,
        timeout=timeout,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "sec-fetch-dest": "document",
            "sec-fetch-mode": "navigate",
            "sec-fetch-site": "same-origin",
        },
    )
    meta = parse_match_meta(body.decode("utf-8", "replace"), url=url)
    log.info(
        "match meta url=%s scorebotId=%s scorebotUrl=%s team1=%s team2=%s bytes=%s",
        meta.get("url"),
        meta.get("scorebotId"),
        meta.get("scorebotUrl"),
        meta.get("team1"),
        meta.get("team2"),
        len(body),
    )
    return meta
