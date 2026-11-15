from __future__ import annotations

import base64
import json
import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
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
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _list_pages(base: str, timeout: float) -> list[dict]:
    data = _http_json("GET", f"{base.rstrip('/')}/json/list", timeout)
    if not isinstance(data, list):
        return []
    return [p for p in data if isinstance(p, dict)]


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.2) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def vnc_up() -> bool:
    return port_open(6080) or port_open(5900)


def chrome_cgroup_bytes() -> int | None:
    path = "/sys/fs/cgroup/system.slice/hltv-chrome.service/memory.current"
    try:
        return int(open(path, encoding="utf-8").read().strip())
    except (OSError, ValueError):
        return None


def _is_matches_list(url: str) -> bool:
    return urlparse(url).path.rstrip("/") == "/matches"


def _pick_keeper_page(pages: list[dict]) -> dict | None:
    found: list[dict] = []
    lists: list[dict] = []
    for p in pages:
        if p.get("type") != "page":
            continue
        url = str(p.get("url") or "")
        if url.startswith("devtools://") or url.startswith("chrome-extension://"):
            continue
        if "hltv.org" not in url:
            continue
        found.append(p)
        if _is_matches_list(url):
            lists.append(p)
    if lists:
        return lists[0]
    return found[0] if found else None


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

    def recv_msg(self, timeout: float = 1.0) -> dict | None:
        import websocket

        self.ws.settimeout(timeout)
        try:
            raw = self.ws.recv()
        except websocket.WebSocketTimeoutException:
            return None
        except TimeoutError:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        data = json.loads(raw)
        return data if isinstance(data, dict) else None


def _connect_ws(ws_url: str, timeout: float) -> _CdpWs:
    import websocket

    try:
        try:
            ws = websocket.create_connection(
                ws_url,
                origin="http://127.0.0.1:9222",
                timeout=timeout,
            )
        except Exception:
            ws = websocket.create_connection(
                ws_url,
                suppress_origin=True,
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


_FETCH_JS = """\
(async () => {
  const res = await fetch(%s, {credentials: "include", redirect: "follow"});
  const buf = new Uint8Array(await res.arrayBuffer());
  let bin = "";
  const step = 0x8000;
  for (let i = 0; i < buf.length; i += step) {
    bin += String.fromCharCode.apply(null, buf.subarray(i, i + step));
  }
  const headers = {};
  res.headers.forEach((v, k) => { headers[k] = v; });
  return {status: res.status, url: res.url, headers: headers, body: btoa(bin)};
})()
"""


def fetch_via_chrome(
    url: str,
    base: str = DEFAULT_CDP,
    *,
    timeout: float = 25.0,
) -> tuple[int, bytes, dict[str, str]]:
    """GET url inside the existing HLTV tab (cookies stay in Chrome). Attach only."""
    pages = _list_pages(base, min(timeout, 5.0))
    page = _pick_keeper_page(pages)
    if page is None:
        raise CdpUnavailable("no hltv.org page for fetch")
    ws_url = str(page.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise CdpUnavailable("missing webSocketDebuggerUrl")
    client = _connect_ws(ws_url, timeout)
    try:
        try:
            client.call("Runtime.enable", timeout=min(timeout, 5.0))
        except CdpError:
            pass
        ev = client.call(
            "Runtime.evaluate",
            {
                "expression": _FETCH_JS % json.dumps(url),
                "awaitPromise": True,
                "returnByValue": True,
            },
            timeout=timeout,
        )
        if ev.get("exceptionDetails"):
            raise CdpError(str(ev.get("exceptionDetails")))
        inner = ev.get("result") if isinstance(ev.get("result"), dict) else {}
        val = inner.get("value") if isinstance(inner.get("value"), dict) else {}
        status = int(val.get("status") or 0)
        body_b64 = str(val.get("body") or "")
        body = base64.b64decode(body_b64) if body_b64 else b""
        raw_h = val.get("headers") if isinstance(val.get("headers"), dict) else {}
        headers = {str(k).lower(): str(v) for k, v in raw_h.items()}
        log.debug("chrome fetch %s status=%s bytes=%s", url, status, len(body))
        return status, body, headers
    finally:
        try:
            client.ws.close()
        except Exception:
            pass


def close_extra_pages(
    base: str = DEFAULT_CDP,
    *,
    keep_path: str = "/matches",
    keep_urls: list[str] | None = None,
    timeout: float = 3.0,
) -> int:
    """Drop extra HLTV tabs; keep keeper /matches and optional watch URL. Skip when VNC is up."""
    if vnc_up():
        return 0
    keep = tuple(u.rstrip("/") for u in (keep_urls or []) if u)
    pages = _list_pages(base, timeout)
    n = 0
    for p in pages:
        if p.get("type") != "page":
            continue
        url = str(p.get("url") or "")
        if "hltv.org" not in url:
            continue
        parsed = urlparse(url)
        path = (parsed.path or "").rstrip("/")
        if path == keep_path.rstrip("/") or path == "":
            continue
        # Keep if URL starts with or contains any keep target, or if same match id /matches/<id>/
        def _matches_keep(u: str, targets: tuple[str, ...]) -> bool:
            u_path = urlparse(u).path.rstrip("/")
            for k in targets:
                if not k:
                    continue
                if u.startswith(k) or k in u:
                    return True
                k_path = urlparse(k).path.rstrip("/")
                # If /matches/12345/x, check /matches/12345/ prefix
                k_parts = [p for p in k_path.split("/") if p]
                u_parts = [p for p in u_path.split("/") if p]
                if len(k_parts) >= 2 and len(u_parts) >= 2:
                    if k_parts[0] == "matches" and u_parts[0] == "matches" and k_parts[1] == u_parts[1]:
                        return True
            return False

        if _matches_keep(url, keep):
            continue
        tid = str(p.get("id") or "")
        if not tid:
            continue
        try:
            _http_json("GET", f"{base.rstrip('/')}/json/close/{tid}", timeout)
            n += 1
        except (CdpError, CdpUnavailable):
            log.debug("close tab failed id=%s", tid)
    if n:
        log.info("closed extra chrome tabs n=%s", n)
    return n
