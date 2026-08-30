"""HLTV Scorebot via Engine.IO 3: polling handshake, then WebSocket upgrade.

Browser path: GET polling → sid, then wss://…/socket.io/?transport=websocket&sid=
with 2probe / 3probe / 5. Events and readyForMatch stay on the WS.
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
    encode_event,
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


def http_to_ws(base: str) -> str:
    b = (base or "").rstrip("/")
    if b.startswith("https://"):
        return "wss://" + b[len("https://") :]
    if b.startswith("http://"):
        return "ws://" + b[len("http://") :]
    return b


def _ws_url(base: str, extra: dict[str, str] | None = None) -> str:
    q = {"EIO": "3", "transport": "websocket", "t": str(int(time.time() * 1000))}
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
    """Polling Set-Cookie (`io`) must ride on the WS upgrade; header Cookie can clobber it."""
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


def _ws_headers(headers: dict[str, str]) -> dict[str, str]:
    """Chrome WS upgrade is HTTP/1.1; drop H2-only / cookie header (cookies= instead)."""
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
            log.info("scorebot sid=%s listId=%s upgrading websocket", sid, list_id)
            yield _trace(f"sid={sid} upgrading websocket")

            ws_url = _ws_url(base, {"sid": str(sid)})
            log.debug("ws connect %s", ws_url)
            cookies = merged_ws_cookies(
                sess.cookie,
                getattr(client, "cookies", None),
                getattr(resp, "cookies", None),
            )
            if sid and "io" not in cookies:
                cookies["io"] = str(sid)
            yield _trace("ws cookies=" + ",".join(sorted(cookies)[:12]))
            from curl_cffi.const import CurlHttpVersion

            ws_err: Exception | None = None
            for label, default_hdrs in (("h1", True), ("h1-min", False)):
                try:
                    yield _trace(f"ws connect {label}")
                    ws = client.ws_connect(
                        ws_url,
                        headers=_ws_headers(headers),
                        cookies=cookies,
                        impersonate=sess.impersonate,
                        timeout=None,
                        verify=True,
                        default_headers=default_hdrs,
                        http_version=CurlHttpVersion.V1_1,
                    )
                    ws_err = None
                    break
                except Exception as e:
                    ws_err = e
                    yield _trace(f"ws {label} {clip(e, 100)}")
                    log.warning("ws connect %s failed: %s", label, clip(e, 160))
            if ws is None:
                assert ws_err is not None
                code = _http_status_from_exc(ws_err)
                # Polling already 200: WS 403 is upgrade/WAF, not a dead cookie.
                if code in (403, 429) and not cookies:
                    raise CloudflareError(code, ws_url) from ws_err
                if code and is_poll_5xx(code):
                    raise RuntimeError(f"scorebot ws HTTP {code}") from ws_err
                raise RuntimeError(f"scorebot ws connect: {ws_err}") from ws_err

            extra = probe_upgrade(ws, timeout=WS_PROBE_TIMEOUT)
            yield _trace("ws probe ok")
            emit = encode_event("readyForMatch", ready_for_match_payload(list_id))
            send_eio(ws, emit)
            log.info(
                "scorebot ws ready sid=%s pingInterval=%s extra=%s",
                sid,
                opened.get("pingInterval"),
                len(extra),
            )
            yield _trace(
                f"ws ready pingInterval={opened.get('pingInterval')} extra={len(extra)}"
            )
            yield ("status", {"state": "connected"})
            yield ("tick", None)
            backoff = RECONNECT_MIN
            for name, payload in iter_ws_events(ws, extra=extra):
                yield (name, payload)
            raise RuntimeError("scorebot ws ended")
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
