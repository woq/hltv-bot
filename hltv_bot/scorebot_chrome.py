"""Engine.IO scorebot inside the live Chrome match tab.

Python does not Upgrade. The page's WebSocket carries Origin
https://www.hltv.org and the CF-bound Chrome process.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Iterator
from urllib.parse import urlparse

from hltv_bot.cdp import (
    DEFAULT_CDP,
    CdpError,
    CdpUnavailable,
    _connect_ws,
    _http_json,
    _list_pages,
)
from hltv_bot.debuglog import clip

log = logging.getLogger("hltv_bot.scorebot_chrome")

_SCOREBOT_JS = r"""
(function(listId, httpBase) {
  if (window.__hltvBotScorebot && window.__hltvBotScorebot.stop) {
    window.__hltvBotScorebot.stop();
  }
  const emit = (name, payload) => {
    try { hltvBotEvent(JSON.stringify({name: name, payload: payload})); } catch (e) {}
  };
  let ws = null;
  let stopped = false;
  window.__hltvBotScorebot = { stop: function() { stopped = true; try { if (ws) ws.close(); } catch (e) {} } };

  function packets(text) {
    if (!text) return [];
    if (text.indexOf("\x1e") >= 0) return text.split("\x1e").filter(Boolean);
    if (/^\d+:/.test(text)) {
      const out = [];
      let s = text;
      while (s.length) {
        const i = s.indexOf(":");
        if (i < 0) { out.push(s); break; }
        const n = parseInt(s.slice(0, i), 10);
        s = s.slice(i + 1);
        out.push(s.slice(0, n));
        s = s.slice(n);
      }
      return out;
    }
    return [text];
  }
  function parseEvent(pkt) {
    if (!pkt || pkt.slice(0, 2) !== "42") return null;
    try {
      const arr = JSON.parse(pkt.slice(2));
      if (!arr || !arr.length) return null;
      let payload = arr[1];
      if (typeof payload === "string") {
        try { payload = JSON.parse(payload); } catch (e) {}
      }
      return {name: arr[0], payload: payload};
    } catch (e) { return null; }
  }
  function readyPkt() {
    const inner = JSON.stringify({token: "", listId: String(listId)});
    return "42" + JSON.stringify(["readyForMatch", inner]);
  }
  function openWs(sid) {
    const wsBase = httpBase.replace(/^http/i, "ws");
    let u = wsBase.replace(/\/$/, "") + "/socket.io/?EIO=3&transport=websocket";
    if (sid) u += "&sid=" + encodeURIComponent(sid);
    const sock = new WebSocket(u);
    ws = sock;
    sock.onopen = function() { sock.send("2probe"); };
    sock.onmessage = function(ev) {
      const d = String(ev.data);
      if (d === "3probe") {
        sock.send("5");
        sock.send(readyPkt());
        emit("status", {state: "connected", transport: "ws"});
        return;
      }
      if (d === "2") { sock.send("3"); return; }
      if (d.charAt(0) === "0") {
        try {
          const o = JSON.parse(d.slice(1));
          emit("trace", {text: "ws open sid=" + (o.sid || sid || "")});
        } catch (e) {}
        sock.send("2probe");
        return;
      }
      if (d === "40") { sock.send(readyPkt()); return; }
      const evp = parseEvent(d);
      if (evp) emit(evp.name, evp.payload);
    };
    sock.onerror = function() { emit("trace", {text: "ws error"}); };
    sock.onclose = function() {
      if (!stopped) emit("status", {state: "reconnect", detail: "ws close", wait: 15});
    };
  }
  async function handshake() {
    emit("status", {state: "connecting", transport: "chrome"});
    const u = httpBase.replace(/\/$/, "") + "/socket.io/?EIO=3&transport=polling&t=" + Date.now();
    let sid = "";
    try {
      const r = await fetch(u, {credentials: "include", mode: "cors"});
      const text = await r.text();
      emit("trace", {text: "handshake HTTP " + r.status + " bytes=" + text.length});
      if (r.status === 403 || r.status === 429) {
        emit("status", {state: "disconnected", detail: "Cloudflare " + r.status});
        return;
      }
      for (const pkt of packets(text)) {
        if (pkt.charAt(0) === "0") {
          const o = JSON.parse(pkt.slice(1));
          sid = o.sid || "";
        }
        const evp = parseEvent(pkt);
        if (evp) emit(evp.name, evp.payload);
      }
    } catch (e) {
      emit("trace", {text: "handshake fetch " + String(e)});
    }
    openWs(sid);
  }
  handshake();
})(%s, %s);
"""


def chrome_scorebot_enabled() -> bool:
    mode = (os.environ.get("HLTV_SCOREBOT") or "chrome").strip().lower()
    if mode in {"curl", "cffi", "off", "0"}:
        return False
    from hltv_bot.cdp import port_open

    return port_open(9222)


def _pick_match_page(pages: list[dict], match_url: str, list_id: str) -> dict | None:
    found: list[dict] = []
    needle = str(list_id or "")
    want = (match_url or "").split("?")[0].rstrip("/")
    for p in pages:
        if p.get("type") != "page":
            continue
        url = str(p.get("url") or "")
        if "hltv.org" not in url or "/matches/" not in url:
            continue
        if "/matches" == urlparse(url).path.rstrip("/"):
            continue
        found.append(p)
        if want and url.startswith(want):
            return p
        if needle and needle in url:
            return p
    return found[0] if found else None


def _ensure_match_tab(
    cdp: str,
    match_url: str,
    list_id: str,
    *,
    timeout: float = 5.0,
) -> dict:
    pages = _list_pages(cdp, timeout)
    page = _pick_match_page(pages, match_url, list_id)
    if page is not None:
        return page
    if not match_url:
        raise CdpUnavailable("no match url for chrome scorebot")
    new_url = f"{cdp.rstrip('/')}/json/new?{match_url}"
    try:
        _http_json("PUT", new_url, timeout)
    except CdpError:
        _http_json("GET", new_url, timeout)
    time.sleep(2.0)
    pages = _list_pages(cdp, timeout)
    page = _pick_match_page(pages, match_url, list_id)
    if page is None:
        raise CdpUnavailable("failed to open match tab")
    return page


def iter_scorebot_chrome(
    list_id: str | int,
    *,
    base: str,
    match_url: str | None = None,
    cdp: str = DEFAULT_CDP,
    timeout: float = 25.0,
) -> Iterator[tuple[str, Any]]:
    list_id = str(list_id)
    match_url = (match_url or "").strip() or f"https://www.hltv.org/matches/{list_id}/x"
    log.info("scorebot chrome listId=%s tab=%s base=%s", list_id, match_url, base)
    page = _ensure_match_tab(cdp, match_url, list_id)
    ws_url = str(page.get("webSocketDebuggerUrl") or "")
    if not ws_url:
        raise CdpUnavailable("match tab has no debugger url")
    client = _connect_ws(ws_url, timeout)
    yield ("status", {"state": "connecting", "transport": "chrome"})
    yield ("trace", {"text": f"chrome tab {page.get('url')}"})
    try:
        for method in ("Runtime.enable", "Page.enable"):
            try:
                client.call(method, timeout=5.0)
            except CdpError:
                pass
        client.call("Runtime.addBinding", {"name": "hltvBotEvent"}, timeout=5.0)
        expr = _SCOREBOT_JS % (json.dumps(list_id), json.dumps(base.rstrip("/")))
        ev = client.call(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True},
            timeout=timeout,
        )
        if ev.get("exceptionDetails"):
            raise CdpError(str(ev.get("exceptionDetails")))
        while True:
            msg = client.recv_msg(1.0)
            if msg is None:
                yield ("tick", None)
                continue
            if msg.get("method") != "Runtime.bindingCalled":
                continue
            params = msg.get("params") if isinstance(msg.get("params"), dict) else {}
            if params.get("name") != "hltvBotEvent":
                continue
            try:
                data = json.loads(str(params.get("payload") or ""))
            except json.JSONDecodeError:
                continue
            name = data.get("name")
            payload = data.get("payload")
            if not name:
                continue
            yield (str(name), payload)
    finally:
        try:
            client.call(
                "Runtime.evaluate",
                {"expression": "window.__hltvBotScorebot && window.__hltvBotScorebot.stop()", "returnByValue": True},
                timeout=3.0,
            )
        except Exception:
            pass
        try:
            client.ws.close()
        except Exception:
            pass
        log.info("scorebot chrome stopped listId=%s", list_id)
