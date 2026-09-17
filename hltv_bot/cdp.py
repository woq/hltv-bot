from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hltv_bot.session import is_challenge_cdp

log = logging.getLogger("hltv_bot.cdp")

DEFAULT_CDP = "http://127.0.0.1:9222"
KEEPER_URL = "https://www.hltv.org/matches"
CDP_ORIGIN = "http://127.0.0.1:9222"


class CdpUnavailable(Exception):
    pass


class CdpError(Exception):
    pass


@dataclass
class CdpSnapshot:
    title: str
    url: str
    cookies: list[dict]
    screenshot_png: bytes | None
    created_new_tab: bool = False


def _http_json(method: str, url: str, timeout: float) -> Any:
    req = Request(url, method=method)
    try:
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        raise CdpError(f"CDP HTTP {e.code} {url}") from e
    except URLError as e:
        raise CdpUnavailable(str(getattr(e, "reason", e))) from e
    except OSError as e:
        raise CdpUnavailable(str(e)) from e
    if not raw:
        return None
    return json.loads(raw)


def _list_pages(base: str, timeout: float) -> list[dict]:
    data = _http_json("GET", f"{base.rstrip('/')}/json/list", timeout)
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]


def _pick_keeper_page(pages: list[dict]) -> dict | None:
    found: list[dict] = []
    for p in pages:
        if p.get("type") != "page":
            continue
        url = str(p.get("url") or "")
        if url.startswith("devtools://") or url.startswith("chrome-extension://"):
            continue
        if "hltv.org" not in url:
            continue
        found.append(p)
    if not found:
        return None
    matches = [p for p in found if "/matches" in str(p.get("url") or "")]
    return (matches or found)[0]


class _CdpWs:
    def __init__(self, ws: Any):
        self.ws = ws
        self._n = 0

    def call(self, method: str, params: dict | None = None, timeout: float = 5.0) -> dict:
        self._n += 1
        msg_id = self._n
        payload = {"id": msg_id, "method": method}
        if params:
            payload["params"] = params
        self.ws.send(json.dumps(payload))
        deadline = timeout
        import time

        t0 = time.monotonic()
        while True:
            remaining = deadline - (time.monotonic() - t0)
            if remaining <= 0:
                raise CdpError(f"CDP timeout {method}")
            self.ws.settimeout(remaining)
            raw = self.ws.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            data = json.loads(raw)
            if data.get("id") != msg_id:
                continue
            if data.get("error"):
                raise CdpError(f"{method}: {data['error']}")
            result = data.get("result")
            return result if isinstance(result, dict) else {}


def _connect_ws(ws_url: str, timeout: float) -> _CdpWs:
    import websocket

    try:
        ws = websocket.create_connection(
            ws_url,
            origin="http://127.0.0.1:9222",
            timeout=timeout,
        )
    except Exception as e:
        raise CdpUnavailable(str(e)) from e
    return _CdpWs(ws)


def fetch_keeper_snapshot(
    base: str = DEFAULT_CDP,
    *,
    keeper_url: str = KEEPER_URL,
    timeout: float = 5.0,
    sleep: Any = None,
) -> CdpSnapshot:
    """Attach only. Never launch Chrome.

    One WS: title + getAllCookies; screenshot only if
    is_challenge_cdp(title, url, cookies). May PUT /json/new if no hltv page.
    """
    import time as time_mod

    sleeper = time_mod.sleep if sleep is None else sleep
    created = False
    pages = _list_pages(base, timeout)
    page = _pick_keeper_page(pages)
    if page is None:
        new_url = f"{base.rstrip('/')}/json/new?{keeper_url}"
        try:
            _http_json("PUT", new_url, timeout)
        except CdpError:
            _http_json("GET", new_url, timeout)
        created = True
        sleeper(2.0)
        pages = _list_pages(base, timeout)
        page = _pick_keeper_page(pages)
    if page is None:
        raise CdpUnavailable("no hltv.org page")
    ws_url = str(page.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise CdpUnavailable("missing webSocketDebuggerUrl")
    tab_url = str(page.get("url") or keeper_url)
    client = _connect_ws(ws_url, timeout)
    screenshot: bytes | None = None
    title = str(page.get("title") or "")
    cookies: list[dict] = []
    try:
        for method in ("Runtime.enable", "Network.enable", "Page.enable"):
            try:
                client.call(method, timeout=timeout)
            except CdpError:
                log.debug("cdp %s skipped", method)
        ev = client.call(
            "Runtime.evaluate",
            {"expression": "document.title", "returnByValue": True},
            timeout=timeout,
        )
        inner = ev.get("result") if isinstance(ev.get("result"), dict) else {}
        title = str(inner.get("value") or title or "")
        jar = client.call("Network.getAllCookies", timeout=timeout)
        raw_cookies = jar.get("cookies")
        cookies = [c for c in raw_cookies if isinstance(c, dict)] if isinstance(raw_cookies, list) else []
        if is_challenge_cdp(title, tab_url, cookies):
            shot = client.call("Page.captureScreenshot", {"format": "png"}, timeout=timeout)
            b64 = str(shot.get("data") or "")
            if b64:
                screenshot = base64.b64decode(b64)
    finally:
        try:
            client.ws.close()
        except Exception:
            pass
    return CdpSnapshot(
        title=title,
        url=tab_url,
        cookies=cookies,
        screenshot_png=screenshot,
        created_new_tab=created,
    )
