"""HLTV Scorebot via Engine.IO 3.

Prefer WebSocket after the polling handshake. Cloudflare often 403s the
upgrade from curl_cffi; then stay on xhr-polling with the same sid.
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
from hltv_bot.eio import (
    classify_eio,
    decode_payload,
    eio_t,
    encode_event,
    encode_payload,
    parse_event,
    parse_open,
    split_ws_packets,
)
from hltv_bot.session import BrowserSession

log = logging.getLogger("hltv_bot.scorebot")

SCOREBOT_DEFAULT = "https://scorebot-lb.hltv.org"
# Reconnect floor/ceiling. Burst handshake after 502 is what trips WAF/LB.
RECONNECT_MIN = 15.0
RECONNECT_MAX = 180.0
RECONNECT_5XX = 25.0
# Kept for handshake retries / tests. Event stream is WebSocket, not xhr-poll.
POLL_MIN_GAP = 5.0
POLL_EMPTY_GAP = 20.0
POLL_5XX_GAP = 30.0
POLL_5XX_MAX = 4
WS_PROBE_TIMEOUT = 15.0
WS_RETRY_EVERY = 30.0
WS_ATTEMPT_GAP = 1.0
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
    q = {"EIO": "3", "transport": "polling", "t": eio_t()}
    if extra:
        q.update(extra)
    return f"{base.rstrip('/')}/socket.io/?{urlencode(q)}"


def http_to_ws(base: str) -> str:
    b = (base or "").rstrip("/")
    if b.startswith("https://"):
        return "wss://" + b[len("https://") :]
    if b.startswith("http://"):
        return "ws://" + b[len("http://") :]
    return b


def _ws_url(base: str, extra: dict[str, str] | None = None) -> str:
    q = {"EIO": "3", "transport": "websocket", "t": eio_t()}
    if extra:
        q.update(extra)
    return f"{http_to_ws(base)}/socket.io/?{urlencode(q)}"


def _parse_cookie_pairs(raw: object) -> dict[str, str]:
    out: dict[str, str] = {}
    if not raw:
        return out
    if isinstance(raw, dict):
        for k, v in raw.items():
            if k:
                out[str(k)] = str(v)
        return out
    text = str(raw)
    for part in text.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k:
            out[k] = v
    return out


def merged_ws_cookies(session_cookie: str, *sources: object) -> dict[str, str]:
    """Merge session Cookie with handshake Set-Cookie (`io`, `__cflb`, …)."""
    out = _parse_cookie_pairs(session_cookie)
    for src in sources:
        if src is None:
            continue
        if hasattr(src, "items") and not isinstance(src, (str, bytes)):
            try:
                out.update(_parse_cookie_pairs(dict(src.items())))
                continue
            except Exception:
                pass
        out.update(_parse_cookie_pairs(src))
    return out


_COOKIE_FIRST = (
    "io",
    "_cfuvid",
    "__cflb",
    "cf_clearance",
    "__cf_bm",
)


def cookie_header(pairs: dict[str, str]) -> str:
    """Prefer Chrome's CF cookie order; keep the rest as merged."""
    seen: set[str] = set()
    parts: list[str] = []
    for name in _COOKIE_FIRST:
        if name in pairs and pairs[name] and name not in seen:
            parts.append(f"{name}={pairs[name]}")
            seen.add(name)
    for k, v in pairs.items():
        if k and v and k not in seen:
            parts.append(f"{k}={v}")
            seen.add(k)
    return "; ".join(parts)


def ws_upgrade_refused(exc: BaseException) -> bool:
    code = _http_status_from_exc(exc)
    msg = str(exc).lower()
    return code == 403 or "refused websocket upgrade" in msg


def _ws_headers(headers: dict[str, str], *, cookie: str = "") -> dict[str, str]:
    """Chrome WS upgrade is HTTP/1.1; drop H2-only `priority`.

    Do not advertise permessage-deflate or Accept-Encoding: curl_cffi then
    WS_RECVs empty (curl 52) after a successful 101.
    """
    keep = {
        "origin",
        "referer",
        "user-agent",
        "sec-ch-ua",
        "sec-ch-ua-mobile",
        "sec-ch-ua-platform",
        "accept-language",
        "dnt",
    }
    h = {k: v for k, v in headers.items() if k.lower() in keep}
    h["sec-fetch-dest"] = "websocket"
    h["sec-fetch-mode"] = "websocket"
    h["sec-fetch-site"] = "same-site"
    h["cache-control"] = "no-cache"
    h["pragma"] = "no-cache"
    if cookie:
        h["cookie"] = cookie
    return h


def send_eio(ws: Any, packet: str) -> None:
    if hasattr(ws, "send_str"):
        ws.send_str(packet)
        return
    ws.send(packet)


def recv_eio_text(ws: Any) -> str:
    if hasattr(ws, "recv_str"):
        try:
            return ws.recv_str()
        except Exception as e:
            # curl_cffi raises if the frame is not TEXT; fall through to recv().
            if "text frame" not in str(e).lower():
                raise
    data, flags = ws.recv()
    if isinstance(flags, int) and flags & 8:  # CurlWsFlag.CLOSE
        raise RuntimeError("scorebot websocket closed")
    if not data:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return str(data)


def probe_upgrade(ws: Any, *, timeout: float = WS_PROBE_TIMEOUT) -> list[str]:
    """Engine.IO v3 WS probe: client 2probe → server 3probe → client 5."""
    extra: list[str] = []
    send_eio(ws, "2probe")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pkt = recv_eio_text(ws)
        for one in split_ws_packets(pkt):
            if one == "3probe":
                send_eio(ws, "5")
                return extra
            if one == "2":
                send_eio(ws, "3")
                continue
            if one == "2probe":
                send_eio(ws, "3probe")
                continue
            if one in ("3", "6"):
                continue
            extra.append(one)
    raise RuntimeError("scorebot ws probe timeout")


def iter_ws_events(
    ws: Any,
    *,
    extra: list[str] | None = None,
) -> Iterator[tuple[str, Any]]:
    """Read Socket.IO events from an upgraded Engine.IO websocket."""
    pending = list(extra or [])
    idle = 0
    while True:
        if pending:
            pkt = pending.pop(0)
        else:
            raw = recv_eio_text(ws)
            more = split_ws_packets(raw)
            if not more:
                continue
            pkt = more[0]
            pending.extend(more[1:])
        kind, payload = classify_eio(pkt)
        if kind == "ping":
            send_eio(ws, "3probe" if payload == "2probe" else "3")
            idle += 1
            if idle == 3 or idle % 10 == 0:
                yield ("status", {"state": "idle", "misses": idle})
            yield ("tick", None)
            continue
        if kind in {"pong", "noop", "upgrade", "open"}:
            yield ("tick", None)
            continue
        if kind == "close":
            raise RuntimeError("scorebot engine.io close")
        if kind == "event":
            idle = 0
            name, data = payload
            log.debug("event %s %s", name, event_brief(name, data))
            yield (name, data)
            yield ("tick", None)
            continue
        log.debug("ws packet %s", clip(pkt, 160))


def _is_timeout(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "timed out" in msg or "timeout" in msg or "curl: (28)" in msg


_POLL_5XX = frozenset({502, 503, 504, 520, 521, 522, 523, 524})


def is_poll_5xx(status: int) -> bool:
    return status in _POLL_5XX


def _is_http_error(exc: BaseException) -> bool:
    msg = str(exc)
    has_5xx = any(s in msg for s in ("502", "503", "504", "520", "521", "522", "523", "524"))
    return has_5xx and ("HTTP " in msg or "status" in msg.lower() or "ws " in msg.lower())


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


def poll_gap(
    elapsed: float,
    *,
    got_event: bool,
    timed_out: bool = False,
    http_5xx: bool = False,
) -> float:
    """How long to wait after a poll GET before the next one (handshake only)."""
    if http_5xx:
        return POLL_5XX_GAP
    if timed_out:
        return POLL_MIN_GAP
    need = POLL_MIN_GAP if got_event else POLL_EMPTY_GAP
    return max(0.0, need - max(0.0, elapsed))


def _trace(text: str) -> tuple[str, dict[str, str]]:
    return ("trace", {"text": clip(text, 180)})


def _http_status_from_exc(exc: BaseException) -> int | None:
    import re

    m = re.search(
        r"(?:HTTP[ /]|status(?:_code)?[=: ]|ws |upgrade:\s*)(\d{3})",
        str(exc),
        re.I,
    )
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def try_open_ws(
    client: Any,
    *,
    ws_url: str,
    headers: dict[str, str],
    cookies: dict[str, str],
    impersonate: str,
) -> tuple[Any, list[str], Exception | None]:
    """Probe-upgrade. Returns (ws, extra, None) or (None, [], err)."""
    from curl_cffi.const import CurlHttpVersion

    ck_hdr = cookie_header(cookies)
    last: Exception | None = None
    for i, default_hdrs in enumerate((True, False)):
        if i and last is not None:
            if ws_upgrade_refused(last):
                return None, [], last
            time.sleep(WS_ATTEMPT_GAP)
        ws = None
        try:
            ws = client.ws_connect(
                ws_url,
                headers=_ws_headers(headers, cookie=ck_hdr),
                cookies=cookies,
                impersonate=impersonate,
                timeout=None,
                verify=True,
                default_headers=default_hdrs,
                http_version=CurlHttpVersion.V1_1,
            )
            extra = probe_upgrade(ws, timeout=WS_PROBE_TIMEOUT)
            return ws, extra, None
        except Exception as e:
            last = e
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
    return None, [], last


def iter_poll_events(
    client: Any,
    *,
    base: str,
    headers: dict[str, str],
    sid: str,
    list_id: str | int,
    timeout: float,
    skip_ready: bool = False,
    ws_factory: Any | None = None,
    ws_retry_every: float = WS_RETRY_EVERY,
) -> Iterator[tuple[str, Any]]:
    """Engine.IO xhr-polling after handshake (same sid). Retries WS upgrade."""
    from hltv_bot.http import CloudflareError

    if not skip_ready:
        emit = encode_event("readyForMatch", ready_for_match_payload(list_id))
        post_headers = dict(headers)
        post_headers["content-type"] = "text/plain;charset=UTF-8"
        post_url = _poll_url(base, {"sid": sid})
        post_resp = client.post(
            post_url,
            data=encode_payload(emit),
            headers=post_headers,
            timeout=20,
        )
        if post_resp.status_code in (403, 429):
            raise CloudflareError(post_resp.status_code, post_url)
        if post_resp.status_code >= 400:
            raise RuntimeError(f"scorebot readyForMatch HTTP {post_resp.status_code}")
        yield _trace("polling readyForMatch")
        yield ("status", {"state": "connected", "transport": "poll"})
        yield ("tick", None)
    next_ws = 0.0
    misses = 0
    http_fails = 0
    ws_fails = 0
    while True:
        now = time.monotonic()
        if ws_factory and now >= next_ws:
            yield _trace("retry websocket")
            ws, extra, err = ws_factory()
            if ws is not None:
                ws_fails = 0
                yield _trace("ws upgraded")
                yield ("status", {"state": "connected", "transport": "ws"})
                yield ("tick", None)
                for ev in iter_ws_events(ws, extra=extra):
                    yield ev
                return
            ws_fails += 1
            brief = clip(err, 80)
            yield _trace(f"ws retry {brief}")
            yield ("ws_fail", {"error": clip(err, 120), "n": ws_fails})
            next_ws = now + ws_retry_every
        t0 = time.monotonic()
        try:
            resp = client.get(
                _poll_url(base, {"sid": sid}),
                headers=headers,
                timeout=timeout,
            )
        except Exception as e:
            if _is_timeout(e):
                misses += 1
                http_fails = 0
                log.info("poll timeout n=%s (idle ok)", misses)
                if misses == 1 or misses % 5 == 0:
                    yield ("status", {"state": "idle", "misses": misses, "transport": "poll"})
                gap = poll_gap(time.monotonic() - t0, got_event=False, timed_out=True)
                if gap:
                    time.sleep(gap)
                yield ("tick", None)
                continue
            raise
        elapsed = time.monotonic() - t0
        if resp.status_code in (403, 429):
            raise CloudflareError(resp.status_code, str(resp.url))
        if resp.status_code >= 400:
            if not is_poll_5xx(resp.status_code):
                raise RuntimeError(f"scorebot poll HTTP {resp.status_code}")
            http_fails += 1
            log.warning(
                "poll http %s n=%s sid=%s elapsed=%.2fs",
                resp.status_code,
                http_fails,
                sid,
                elapsed,
            )
            yield _trace(f"poll HTTP {resp.status_code} n={http_fails}")
            if http_fails >= POLL_5XX_MAX:
                raise RuntimeError(f"scorebot poll HTTP {resp.status_code}")
            next_ws = 0.0
            gap = poll_gap(elapsed, got_event=False, http_5xx=True)
            yield (
                "status",
                {
                    "state": "connected",
                    "detail": f"poll HTTP {resp.status_code}",
                    "wait": round(gap, 1),
                    "transport": "poll",
                },
            )
            if gap:
                time.sleep(gap)
            continue
        if misses or http_fails:
            yield ("status", {"state": "connected", "transport": "poll"})
        misses = 0
        http_fails = 0
        got = False
        pkts = decode_payload(resp.content or b"")
        for pkt in pkts:
            ev = parse_event(pkt)
            if ev:
                got = True
                log.debug("event %s %s", ev[0], event_brief(ev[0], ev[1]))
                yield ev
        yield ("tick", None)
        gap = poll_gap(elapsed, got_event=got, timed_out=False)
        if gap:
            time.sleep(gap)


def iter_scorebot(
    sess: BrowserSession,
    list_id: str | int,
    *,
    base: str = SCOREBOT_DEFAULT,
    timeout: float = 55.0,
) -> Iterator[tuple[str, Any]]:
    """Yield (event_name, payload). Handshake on polling, then Engine.IO websocket.

    Reuses one TLS session so the Engine.IO `io` cookie from the handshake GET
    is sent on the WS upgrade. timeout is only used for the polling handshake.
    """
    from curl_cffi.requests import Session

    from hltv_bot.http import CloudflareError

    headers = sess.as_headers()
    log.info(
        "scorebot start listId=%s base=%s impersonate=%s transport=websocket",
        list_id,
        base,
        sess.impersonate,
    )

    backoff = RECONNECT_MIN
    while True:
        client = Session(impersonate=sess.impersonate, timeout=timeout, verify=True)
        ws = None
        try:
            yield ("status", {"state": "connecting"})
            yield _trace(f"handshake {base} impersonate={sess.impersonate}")
            sid = None
            opened: dict[str, Any] = {}
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
                    yield _trace(
                        f"handshake HTTP {resp.status_code} bytes={len(resp.content or b'')}"
                    )
                except Exception as e:
                    if _is_timeout(e) and attempt < 3:
                        log.info("handshake timeout, retry %s err=%s", attempt + 1, clip(e, 120))
                        yield _trace(f"handshake timeout attempt={attempt + 1}")
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
                    got = parse_open(pkt)
                    if got and "sid" in got:
                        sid = got["sid"]
                        opened = got
                        log.debug(
                            "handshake open sid=%s pingInterval=%s pingTimeout=%s upgrades=%s",
                            sid,
                            got.get("pingInterval"),
                            got.get("pingTimeout"),
                            got.get("upgrades"),
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
            cookies = merged_ws_cookies(
                sess.cookie,
                headers.get("cookie") or headers.get("Cookie"),
                getattr(client, "cookies", None),
                getattr(resp, "cookies", None),
            )
            if sid and "io" not in cookies:
                cookies["io"] = str(sid)
            ws_url = _ws_url(base, {"sid": str(sid)})
            yield _trace(f"sid={sid} cookies=" + ",".join(sorted(cookies)[:16]))

            def _ws_factory() -> tuple[Any, list[str], Exception | None]:
                return try_open_ws(
                    client,
                    ws_url=ws_url,
                    headers=headers,
                    cookies=cookies,
                    impersonate=sess.impersonate,
                )

            log.info("scorebot sid=%s listId=%s polling then ws", sid, list_id)
            backoff = RECONNECT_MIN
            for ev in iter_poll_events(
                client,
                base=base,
                headers=headers,
                sid=str(sid),
                list_id=list_id,
                timeout=timeout,
                ws_factory=_ws_factory,
            ):
                yield ev
            raise RuntimeError("scorebot session ended")
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
            yield _trace(f"error {clip(e, 120)} retry {wait:.0f}s")
            yield (
                "status",
                {"state": "reconnect", "detail": str(e)[:80], "wait": round(wait, 1)},
            )
            time.sleep(wait)
            backoff = next_backoff(backoff, http_5xx=hot)
            continue
        finally:
            if ws is not None:
                try:
                    ws.close()
                except Exception:
                    pass
            try:
                client.close()
            except Exception:
                pass
