from __future__ import annotations

import re
from html import unescape

from hltv_bot.http import request
from hltv_bot.session import BrowserSession

MATCHES_URL = "https://www.hltv.org/matches"
MATCH_HREF = re.compile(
    r'href="(/matches/(\d+)/[^"]+)"[^>]*>',
)
LIVE_BLOCK = re.compile(
    r'class="[^"]*live-match[^"]*"[\s\S]{0,1200}?href="(/matches/(\d+)/[^"]+)"',
    re.I,
)
SCOREBOT_ID = re.compile(r'data-scorebot-id="(\d+)"')
SCOREBOT_URL = re.compile(r'data-scorebot-url="([^"]+)"')
TEAM1 = re.compile(r'data-team1-name="([^"]*)"')
TEAM2 = re.compile(r'data-team2-name="([^"]*)"')


def _abs(href: str) -> str:
    if href.startswith("http"):
        return href
    return "https://www.hltv.org" + href


def parse_match_list(html: str, *, limit: int = 20) -> list[dict[str, str]]:
    seen: set[str] = set()
    live_ids = {m.group(2) for m in LIVE_BLOCK.finditer(html)}
    rows: list[dict[str, str]] = []
    for m in MATCH_HREF.finditer(html):
        href, mid = m.group(1), m.group(2)
        if mid in seen:
            continue
        seen.add(mid)
        slug = href.rsplit("/", 1)[-1]
        title = unescape(slug.replace("-", " "))
        rows.append(
            {
                "id": mid,
                "url": _abs(href),
                "title": title,
                "live": "1" if mid in live_ids else "0",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def parse_match_meta(html: str, url: str = "") -> dict[str, str | None]:
    def g(rx: re.Pattern[str]) -> str | None:
        m = rx.search(html)
        return unescape(m.group(1)) if m else None

    return {
        "url": url or None,
        "scorebotId": g(SCOREBOT_ID),
        "scorebotUrl": g(SCOREBOT_URL),
        "team1": g(TEAM1),
        "team2": g(TEAM2),
    }


def fetch_matches(sess: BrowserSession, timeout: float = 20.0) -> list[dict[str, str]]:
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
    return parse_match_list(body.decode("utf-8", "replace"))


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
    return parse_match_meta(body.decode("utf-8", "replace"), url=url)
