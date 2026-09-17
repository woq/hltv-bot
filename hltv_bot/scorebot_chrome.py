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
  let reconnectTimer = null;
  let pingTimer = null;
  let handshakeBusy = false;
  let pingInterval = 25000;
  let pingTimeout = 60000;
  let lastPkt = "";
  let pingCount = 0;
  let evCount = 0;
  let openedAt = 0;
  let lastBoard = "";
  window.__hltvBotScorebot = { stop: function() {
    stopped = true;
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
    if (pingTimer) { clearTimeout(pingTimer); pingTimer = null; }
    try { if (ws) ws.close(); } catch (e) {}
  } };

  function clip(s, n) {
    s = String(s || "");
    return s.length > n ? s.slice(0, n) : s;
  }
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
  function sendReady() {
    try { ws.send(readyPkt()); } catch (e) {}
    emit("trace", {text: "readyForMatch listId=" + listId});
  }
  function armPing() {
    if (pingTimer) clearTimeout(pingTimer);
    pingTimer = setTimeout(function() {
      emit("trace", {text: "ws ping timeout interval=" + pingInterval + " timeout=" + pingTimeout});
      try { if (ws) ws.close(); } catch (e) {}
    }, pingInterval + pingTimeout);
  }
  function scheduleReconnect(detail) {
    if (stopped || reconnectTimer) return;
    const wait = 15;
    emit("status", {state: "reconnect", detail: detail, wait: wait});
    reconnectTimer = setTimeout(function() {
      reconnectTimer = null;
      if (!stopped) handshake();
    }, wait * 1000);
  }
  function handlePkt(d, via) {
    lastPkt = clip(d, 24);
    if (d === "3probe") {
      try { ws.send("5"); } catch (e) {}
      sendReady();
      emit("status", {state: "connected", transport: "ws"});
      armPing();
      return;
    }
    if (d === "2") {
      pingCount += 1;
      try { ws.send("3"); } catch (e) {}
      if (pingCount === 1 || pingCount % 10 === 0) {
        emit("trace", {text: "ws ping n=" + pingCount + " pong"});
      }
      armPing();
      return;
    }
    if (d === "1") {
      emit("trace", {text: "eio close packet via=" + via});
      try { if (ws) ws.close(); } catch (e) {}
      return;
    }
    if (d.charAt(0) === "0") {
      try {
        const o = JSON.parse(d.slice(1));
        if (o.pingInterval) pingInterval = o.pingInterval;
        if (o.pingTimeout) pingTimeout = o.pingTimeout;
        emit("trace", {text: "ws open sid=" + (o.sid || "") + " ping=" + pingInterval + "/" + pingTimeout});
      } catch (e) {}
      try { ws.send("2probe"); } catch (e) {}
      armPing();
      return;
    }
    if (d === "40") {
      sendReady();
      return;
    }
    const evp = parseEvent(d);
    if (evp) {
      evCount += 1;
      if (evp.name === "scoreboard") {
        let raw = "";
        try { raw = JSON.stringify(evp.payload); } catch (e) {}
        if (raw && raw === lastBoard) return;
        lastBoard = raw;
      }
      emit(evp.name, evp.payload);
      return;
    }
    if (d && d !== "3" && d !== "6") {
      emit("trace", {text: "ws pkt via=" + via + " " + clip(d, 40)});
    }
  }
  function openWs(sid) {
    if (ws) {
      try { ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.close(); } catch (e) {}
      ws = null;
    }
    const wsBase = httpBase.replace(/^http/i, "ws");
    let u = wsBase.replace(/\/$/, "") + "/socket.io/?EIO=3&transport=websocket";
    if (sid) u += "&sid=" + encodeURIComponent(sid);
    const sock = new WebSocket(u);
    ws = sock;
    openedAt = Date.now();
    pingCount = 0;
    evCount = 0;
    lastBoard = "";
    sock.onopen = function() { sock.send("2probe"); };
    sock.onmessage = function(ev) {
      const raw = ev.data;
      if (typeof raw !== "string") {
        const kind = (raw && raw.constructor && raw.constructor.name) || typeof raw;
        emit("trace", {text: "ws non-text " + kind});
        return;
      }
      const parts = packets(raw);
      for (let i = 0; i < parts.length; i++) handlePkt(parts[i], "ws");
    };
    sock.onerror = function(ev) {
      emit("trace", {text: "ws error " + clip(ev && (ev.message || ev.type), 60)});
    };
    sock.onclose = function(ev) {
      if (pingTimer) { clearTimeout(pingTimer); pingTimer = null; }
      const up = openedAt ? Math.round((Date.now() - openedAt) / 1000) : 0;
      const detail = "ws close code=" + (ev && ev.code) + " clean=" + !!(ev && ev.wasClean)
        + " reason=" + clip(ev && ev.reason, 40);
      emit("trace", {text: detail + " last=" + lastPkt + " pings=" + pingCount + " ev=" + evCount + " up=" + up + "s"});
      if (!stopped) scheduleReconnect("ws close code=" + (ev && ev.code));
    };
  }
  async function handshake() {
    if (stopped || handshakeBusy) return;
    handshakeBusy = true;
    emit("status", {state: "connecting", transport: "chrome"});
    const u = httpBase.replace(/\/$/, "") + "/socket.io/?EIO=3&transport=polling&t=" + Date.now().toString(36);
    let sid = "";
    let openBits = "";
    try {
      const r = await fetch(u, {credentials: "include", mode: "cors"});
      const text = await r.text();
      for (const pkt of packets(text)) {
        if (pkt.charAt(0) === "0") {
          const o = JSON.parse(pkt.slice(1));
          sid = o.sid || "";
          if (o.pingInterval) pingInterval = o.pingInterval;
          if (o.pingTimeout) pingTimeout = o.pingTimeout;
          openBits = " sid=" + sid + " ping=" + pingInterval + "/" + pingTimeout;
        }
        const evp = parseEvent(pkt);
        if (evp) emit(evp.name, evp.payload);
      }
      emit("trace", {text: "handshake HTTP " + r.status + " bytes=" + text.length + openBits});
      if (r.status === 403 || r.status === 429) {
        handshakeBusy = false;
        emit("status", {state: "disconnected", detail: "Cloudflare " + r.status});
        scheduleReconnect("Cloudflare " + r.status);
        return;
      }
    } catch (e) {
      emit("trace", {text: "handshake fetch " + String(e)});
    }
    handshakeBusy = false;
    if (stopped) return;
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
