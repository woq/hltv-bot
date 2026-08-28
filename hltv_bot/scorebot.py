"""HLTV Scorebot via Engine.IO 3 polling + TLS impersonation.

WebSocket upgrade is available (`upgrades: ["websocket"]`) but polling is the
path verified with captured Chrome cookies. Same events: log / scoreboard.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hltv_bot.eio import decode_payload, encode_event, encode_payload, parse_event, parse_open
from hltv_bot.http import request
from hltv_bot.session import BrowserSession

SCOREBOT_DEFAULT = "https://scorebot-lb.hltv.org"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def probe_scorebot(base: str = SCOREBOT_DEFAULT, timeout: float = 8.0) -> dict[str, Any]:
    url = f"{base.rstrip('/')}/socket.io/?EIO=3&transport=polling"
    req = Request(url, headers={"User-Agent": UA, "Origin": "https://www.hltv.org"})
    try:
        with urlopen(req, timeout=timeout) as resp:
            body = resp.read()[:400]
            return {
                "ok": resp.status == 200,
                "status": resp.status,
                "body": body.decode("utf-8", "replace"),
            }
    except HTTPError as e:
        return {
            "ok": False,
            "status": e.code,
            "cloudflare": e.headers.get("cf-mitigated") == "challenge",
            "server": e.headers.get("server"),
            "body": e.read()[:200].decode("utf-8", "replace"),
        }
    except URLError as e:
        return {"ok": False, "error": str(e.reason)}


def ready_for_match_payload(list_id: str | int, token: str = "") -> str:
    return json.dumps({"token": token, "listId": str(list_id)})


def scorebot_base(url: str | None) -> str:
    raw = (url or SCOREBOT_DEFAULT).split(",")[-1].strip()
    return raw or SCOREBOT_DEFAULT


OnEvent = Callable[[str, Any], None]


def _poll_url(base: str, extra: dict[str, str] | None = None) -> str:
    q = {"EIO": "3", "transport": "polling", "t": str(int(time.time() * 1000))}
    if extra:
        q.update(extra)
    return f"{base.rstrip('/')}/socket.io/?{urlencode(q)}"


def iter_scorebot(
    sess: BrowserSession,
    list_id: str | int,
    *,
    base: str = SCOREBOT_DEFAULT,
    timeout: float = 30.0,
) -> Iterator[tuple[str, Any]]:
    """Yield (event_name, payload) until the caller stops iterating."""
    status, body, _ = request(sess, "GET", _poll_url(base), timeout=timeout)
    sid = None
    for pkt in decode_payload(body):
        opened = parse_open(pkt)
        if opened and "sid" in opened:
            sid = opened["sid"]
        ev = parse_event(pkt)
        if ev:
            yield ev
    if not sid:
        raise RuntimeError(f"scorebot handshake failed status={status}")

    emit = encode_event("readyForMatch", ready_for_match_payload(list_id))
    request(
        sess,
        "POST",
        _poll_url(base, {"sid": sid}),
        data=encode_payload(emit),
        timeout=timeout,
        headers={"content-type": "text/plain;charset=UTF-8"},
    )

    while True:
        _st, body, _hdrs = request(
            sess, "GET", _poll_url(base, {"sid": sid}), timeout=timeout
        )
        for pkt in decode_payload(body):
            ev = parse_event(pkt)
            if ev:
                yield ev
