"""Browser request profile captured from Chrome MCP (Chrome 134 / Windows).

Header names and order follow a live scorebot-lb request, not a made-up set.
TLS impersonate string is chosen at runtime to the closest curl_cffi chrome.
"""

from __future__ import annotations

# Closest curl_cffi targets to MCP Chrome/134; first available wins.
IMPERSONATE_CANDIDATES = (
    "chrome136",
    "chrome133",
    "chrome131",
    "chrome124",
    "chrome120",
    "chrome119",
    "chrome116",
)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
)

# Order matches the captured scorebot GET (HTTP/2 pseudo-headers omitted).
HEADER_ORDER = (
    "sec-ch-ua-platform",
    "referer",
    "user-agent",
    "sec-ch-ua",
    "dnt",
    "sec-ch-ua-mobile",
    "accept",
    "accept-encoding",
    "accept-language",
    "origin",
    "priority",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
)


def pick_impersonate(preferred: str | None = None) -> str:
    names: list[str] = []
    if preferred:
        names.append(preferred)
    names.extend(IMPERSONATE_CANDIDATES)
    try:
        from curl_cffi.requests import BrowserType
        allowed = {str(x).split(".")[-1] for x in BrowserType}
    except Exception:
        allowed = set(IMPERSONATE_CANDIDATES)
    for name in names:
        key = name.replace("BrowserType.", "")
        if key in allowed or name in allowed:
            return key
        if not allowed:
            return name
    return names[0]


def build_headers(
    *,
    user_agent: str = DEFAULT_UA,
    sec_ch_ua: str = '"Chromium";v="134", "Not:A-Brand";v="24", "Google Chrome";v="134"',
    sec_ch_ua_mobile: str = "?0",
    sec_ch_ua_platform: str = '"Windows"',
    accept_language: str = "zh-CN,zh;q=0.9,zh-TW;q=0.8",
    dnt: str = "1",
    accept: str = "*/*",
    origin: str = "https://www.hltv.org",
    referer: str = "https://www.hltv.org/",
    fetch_dest: str = "empty",
    fetch_mode: str = "cors",
    fetch_site: str = "same-site",
) -> dict[str, str]:
    raw = {
        "sec-ch-ua-platform": sec_ch_ua_platform,
        "referer": referer,
        "user-agent": user_agent,
        "sec-ch-ua": sec_ch_ua,
        "dnt": dnt,
        "sec-ch-ua-mobile": sec_ch_ua_mobile,
        "accept": accept,
        "accept-encoding": "gzip, deflate, br, zstd",
        "accept-language": accept_language,
        "origin": origin,
        "priority": "u=1, i",
        "sec-fetch-dest": fetch_dest,
        "sec-fetch-mode": fetch_mode,
        "sec-fetch-site": fetch_site,
    }
    return {k: raw[k] for k in HEADER_ORDER if k in raw}
