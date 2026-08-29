"""HLTV Scorebot via Engine.IO 3 polling + TLS impersonation.

WebSocket upgrade is available (`upgrades: ["websocket"]`) but polling is the
path verified with captured Chrome cookies. Same events: log / scoreboard.
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hltv_bot.debuglog import clip, event_brief
from hltv_bot.eio import decode_payload, encode_event, encode_payload, parse_event, parse_open
from hltv_bot.http import request
from hltv_bot.session import BrowserSession

log = logging.getLogger("hltv_bot.scorebot")

SCOREBOT_DEFAULT = "https://scorebot-lb.hltv.org"
# Reconnect floor/ceiling. Burst handshake after 502 is what trips WAF/LB.
RECONNECT_MIN = 15.0
RECONNECT_MAX = 180.0
RECONNECT_5XX = 25.0
# Engine.IO long-poll normally blocks ~25s. 400ms was RTT of HTTP 502 then
# immediate next GET — not a configured interval. Floor every poll.
POLL_MIN_GAP = 2.0
POLL_EMPTY_GAP = 10.0
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


def _is_http_error(exc: BaseException) -> bool:
    msg = str(exc)
    return "HTTP " in msg or "status" in msg.lower() and any(
        s in msg for s in ("502", "503", "504", "520", "521", "522", "523", "524")
    )


def reconnect_wait(backoff: float, *, http_5xx: bool = False) -> float:
    """Seconds to sleep before the next handshake. Never below RECONNECT_MIN."""
    floor = RECONNECT_5XX if http_5xx else RECONNECT_MIN
    base = max(float(backoff or 0), floor, RECONNECT_MIN)
    base = min(base, RECONNECT_MAX)
    wait = base * (0.85 + random.random() * 0.3)
    return min(max(wait, RECONNECT_MIN), RECONNECT_MAX)


def next_backoff(backoff: float, *, http_5xx: bool = False) -> float:
    floor = RECONNECT_5XX if http_5xx else RECONNECT_MIN
    cur = max(float(backoff or 0), floor, RECONNECT_MIN)
    return min(cur * 2.0, RECONNECT_MAX)


def poll_gap(elapsed: float, *, got_event: bool, timed_out: bool = False) -> float:
    """How long to wait after a poll GET before the next one."""
    if timed_out:
        return POLL_MIN_GAP
    need = POLL_MIN_GAP if got_event else POLL_EMPTY_GAP
    return max(0.0, need - max(0.0, elapsed))


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
    from curl_cffi.requests import Session

    headers = sess.as_headers()
    log.info("scorebot start listId=%s base=%s impersonate=%s", list_id, base, sess.impersonate)
    from hltv_bot.http import CloudflareError

    backoff = RECONNECT_MIN
    while True:
        client = Session(impersonate=sess.impersonate, timeout=timeout, verify=True)
        try:
            yield ("status", {"state": "connecting"})
            sid = None
            for attempt in range(4):
                try:
                    url = _poll_url(base)
                    log.debug("handshake GET %s attempt=%s", url, attempt)
                    resp = client.get(url, headers=headers)
                    log.debug(
                        "handshake status=%s bytes=%s",
                        resp.status_code,
                        len(resp.content or b""),
                    )
                except Exception as e:
                    if _is_timeout(e) and attempt < 3:
                        log.info("handshake timeout, retry %s err=%s", attempt + 1, clip(e, 120))
                        yield (
                            "status",
                            {
                                "state": "reconnect",
                                "detail": "handshake timeout",
                                "wait": RECONNECT_MIN,
                            },
                        )
                        time.sleep(RECONNECT_MIN)
                        continue
                    raise
                if resp.status_code in (403, 429):
                    raise CloudflareError(resp.status_code, str(resp.url))
                if resp.status_code >= 400:
                    raise RuntimeError(f"scorebot handshake HTTP {resp.status_code}")
                for pkt in decode_payload(resp.content):
                    opened = parse_open(pkt)
                    if opened and "sid" in opened:
                        sid = opened["sid"]
                        log.debug(
                            "handshake open sid=%s pingInterval=%s pingTimeout=%s upgrades=%s",
                            sid,
                            opened.get("pingInterval"),
                            opened.get("pingTimeout"),
                            opened.get("upgrades"),
                        )
                    ev = parse_event(pkt)
                    if ev:
                        log.debug("handshake event %s %s", ev[0], event_brief(ev[0], ev[1]))
                        yield ev
                if sid:
                    break
                time.sleep(RECONNECT_MIN)
            if not sid:
                raise RuntimeError("scorebot handshake: no sid")
            log.info("scorebot sid=%s listId=%s", sid, list_id)
            yield ("status", {"state": "connected"})
            yield ("tick", None)
            backoff = RECONNECT_MIN

            emit = encode_event("readyForMatch", ready_for_match_payload(list_id))
            post_headers = dict(headers)
            post_headers["content-type"] = "text/plain;charset=UTF-8"
            post_url = _poll_url(base, {"sid": sid})
            log.debug("readyForMatch POST sid=%s listId=%s pkt=%s", sid, list_id, clip(emit, 200))
            post_resp = client.post(
                post_url,
                data=encode_payload(emit),
                headers=post_headers,
                timeout=20,
            )
            log.debug(
                "readyForMatch status=%s bytes=%s",
                post_resp.status_code,
                len(post_resp.content or b""),
            )
            if post_resp.status_code in (403, 429):
                raise CloudflareError(post_resp.status_code, post_url)
            if post_resp.status_code >= 400:
                raise RuntimeError(f"scorebot readyForMatch HTTP {post_resp.status_code}")

            misses = 0
            while True:
                t0 = time.monotonic()
                timed_out = False
                try:
                    resp = client.get(
                        _poll_url(base, {"sid": sid}),
                        headers=headers,
                        timeout=timeout,
                    )
                except Exception as e:
                    if _is_timeout(e):
                        timed_out = True
                        misses += 1
                        log.info("poll timeout n=%s (idle ok)", misses)
                        if misses == 1 or misses % 5 == 0:
                            yield ("status", {"state": "idle", "misses": misses})
                        gap = poll_gap(time.monotonic() - t0, got_event=False, timed_out=True)
                        if gap:
                            time.sleep(gap)
                        continue
                    raise
                elapsed = time.monotonic() - t0
                if resp.status_code in (403, 429):
                    raise CloudflareError(resp.status_code, str(resp.url))
                if resp.status_code >= 400:
                    log.warning(
                        "poll http %s sid=%s elapsed=%.2fs bytes=%s body=%s",
                        resp.status_code,
                        sid,
                        elapsed,
                        len(resp.content or b""),
                        clip((resp.content or b"")[:180], 180),
                    )
                    raise RuntimeError(f"scorebot poll HTTP {resp.status_code}")
                if misses:
                    yield ("status", {"state": "connected"})
                misses = 0
                got = False
                pkts = decode_payload(resp.content or b"")
                log.debug(
                    "poll sid=%s status=%s elapsed=%.2fs bytes=%s packets=%s",
                    sid,
                    resp.status_code,
                    elapsed,
                    len(resp.content or b""),
                    len(pkts),
                )
                for pkt in pkts:
                    ev = parse_event(pkt)
                    if ev:
                        got = True
                        log.debug("event %s %s", ev[0], event_brief(ev[0], ev[1]))
                        yield ev
                    else:
                        log.debug("packet %s", clip(pkt, 160))
                if not got:
                    log.debug("poll empty sid=%s elapsed=%.2fs", sid, elapsed)
                yield ("tick", None)
                gap = poll_gap(elapsed, got_event=got, timed_out=timed_out)
                if gap:
                    log.debug("poll gap %.1fs (got=%s elapsed=%.2fs)", gap, got, elapsed)
                    time.sleep(gap)
        except CloudflareError as e:
            yield (
                "status",
                {"state": "disconnected", "detail": f"Cloudflare {e.status} · /cookie"},
            )
            raise
        except Exception as e:
            hot = _is_http_error(e)
            wait = reconnect_wait(backoff, http_5xx=hot)
            log.info(
                "scorebot error, reconnect in %.1fs (backoff=%.0fs 5xx=%s): %s",
                wait,
                backoff,
                hot,
                e,
            )
            yield (
                "status",
                {"state": "reconnect", "detail": str(e)[:80], "wait": round(wait, 1)},
            )
            time.sleep(wait)
            backoff = next_backoff(backoff, http_5xx=hot)
            continue
        finally:
            try:
                client.close()
            except Exception:
                pass
