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


def _is_timeout(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg or "curl: (28)" in msg


def iter_scorebot(
    sess: BrowserSession,
    list_id: str | int,
    *,
    base: str = SCOREBOT_DEFAULT,
    timeout: float = 55.0,
) -> Iterator[tuple[str, Any]]:
    """Yield (event_name, payload). Reuses one TLS session so Engine.IO `io` cookie sticks.

    Long-poll GET may wait ~pingInterval (25s) with no bytes; treat curl 28 as empty poll.
    """
    import logging

    from curl_cffi.requests import Session

    log = logging.getLogger("hltv_bot.scorebot")
    headers = sess.as_headers()
    from hltv_bot.http import CloudflareError

    backoff = 1.0
    while True:
        client = Session(impersonate=sess.impersonate, timeout=timeout, verify=True)
        try:
            yield ("status", {"state": "connecting"})
            sid = None
            for attempt in range(4):
                try:
                    resp = client.get(_poll_url(base), headers=headers)
                except Exception as e:
                    if _is_timeout(e) and attempt < 3:
                        log.info("handshake timeout, retry %s", attempt + 1)
                        yield ("status", {"state": "reconnect", "detail": "handshake timeout"})
                        time.sleep(1)
                        continue
                    raise
                if resp.status_code in (403, 429):
                    raise CloudflareError(resp.status_code, str(resp.url))
                for pkt in decode_payload(resp.content):
                    opened = parse_open(pkt)
                    if opened and "sid" in opened:
                        sid = opened["sid"]
                    ev = parse_event(pkt)
                    if ev:
                        yield ev
                if sid:
                    break
                time.sleep(1)
            if not sid:
                raise RuntimeError("scorebot handshake: no sid")
            log.info("scorebot sid=%s listId=%s", sid, list_id)
            yield ("status", {"state": "connected"})
            yield ("tick", None)
            backoff = 1.0

            emit = encode_event("readyForMatch", ready_for_match_payload(list_id))
            post_headers = dict(headers)
            post_headers["content-type"] = "text/plain;charset=UTF-8"
            client.post(
                _poll_url(base, {"sid": sid}),
                data=encode_payload(emit),
                headers=post_headers,
                timeout=20,
            )

            misses = 0
            while True:
                try:
                    resp = client.get(
                        _poll_url(base, {"sid": sid}),
                        headers=headers,
                        timeout=timeout,
                    )
                except Exception as e:
                    if _is_timeout(e):
                        misses += 1
                        log.info("poll timeout n=%s (idle ok)", misses)
                        if misses == 1 or misses % 5 == 0:
                            yield ("status", {"state": "idle", "misses": misses})
                        continue
                    raise
                if resp.status_code in (403, 429):
                    raise CloudflareError(resp.status_code, str(resp.url))
                if misses:
                    yield ("status", {"state": "connected"})
                misses = 0
                got = False
                for pkt in decode_payload(resp.content or b""):
                    ev = parse_event(pkt)
                    if ev:
                        got = True
                        yield ev
                if not got:
                    log.debug("poll empty sid=%s", sid)
                yield ("tick", None)
        except CloudflareError:
            yield ("status", {"state": "disconnected", "detail": "cloudflare"})
            raise
        except Exception as e:
            log.info("scorebot error, reconnect: %s", e)
            yield ("status", {"state": "reconnect", "detail": str(e)[:80]})
            time.sleep(backoff)
            backoff = min(backoff * 2, 20)
            continue
        finally:
            try:
                client.close()
            except Exception:
                pass
