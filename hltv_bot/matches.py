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
_MATCH_CACHE_TTL = 45.0
MATCH_HREF = re.compile(r'href="(/matches/(\d+)/([^"]+))"')
TEAM_NAME = re.compile(
    r'class="[^"]*matchTeamName[^"]*"[^>]*>(?:<[^>]+>)*\s*([^<]+)',
    re.I,
)
EVENT_NAME = re.compile(
    r'class="[^"]*matchEvent(?:Name)?[^"]*"[^>]*>(?:<[^>]+>)*\s*([^<]+)',
    re.I,
)
DATA_STARS = re.compile(r'data-(?:stars|star-rating|rating)="(\d)"', re.I)
DATA_UNIX = re.compile(r'data-unix="(\d{10,13})"')
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
        return pretty, "", ""
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


def parse_match_list(html: str, *, limit: int = 40) -> list[dict[str, str]]:
    seen: set[str] = set()
    rows: list[dict[str, str]] = []
    for m in MATCH_HREF.finditer(html):
        href, mid, slug = m.group(1), m.group(2), m.group(3)
        if mid in seen:
            continue
        seen.add(mid)
        chunk = _chunk_around(html, m.start())
        prefix = html[max(0, m.start() - 1200) : m.start()]
        live_at = [x.start() for x in re.finditer(r"liveMatch|live-match", prefix, re.I)]
        up_at = [x.start() for x in re.finditer(r"upcomingMatch|upcoming-match", prefix, re.I)]
        last_live = max(live_at) if live_at else -1
        last_up = max(up_at) if up_at else -1
        live = last_live > last_up
        teams = [_clean(x) for x in TEAM_NAME.findall(chunk) if _clean(x)]
        t1, t2, event = _teams_event_from_slug(slug)
        if len(teams) >= 2:
            t1, t2 = teams[0], teams[1]
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
        time_s = format_start_time(unix, live=live)
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
    rows.sort(key=lambda r: (0 if r["live"] == "1" else 1, -int(r["stars"])))
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
