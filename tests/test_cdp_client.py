import json
from pathlib import Path
from urllib.error import URLError

import pytest

from hltv_bot.cdp import CdpUnavailable, _CdpWs, _pick_keeper_page, fetch_keeper_snapshot


def test_pick_keeper_prefers_list_over_match_tab():
    pages = [
        {
            "type": "page",
            "url": "https://www.hltv.org/matches/2398088/mouz-vs-nrg",
            "id": "match",
        },
        {
            "type": "page",
            "url": "https://www.hltv.org/matches",
            "id": "list",
        },
    ]
    got = _pick_keeper_page(pages)
    assert got is not None
    assert got["id"] == "list"


def test_cdp_origin_literal():
    src = Path("hltv_bot/cdp.py").read_text(encoding="utf-8")
    assert 'origin="http://127.0.0.1:9222"' in src
    assert "curl_cffi" not in src


class _Resp:
    def __init__(self, body):
        self._body = body.encode("utf-8") if isinstance(body, str) else body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Ws:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent = []

    def send(self, data):
        self.sent.append(data)

    def settimeout(self, t):
        pass

    def recv(self):
        payload = json.loads(self.sent[-1])
        msg_id = payload["id"]
        method = payload["method"]
        if method == "Runtime.evaluate":
            result = {"result": {"value": "Matches"}}
        elif method == "Network.getAllCookies":
            result = {
                "cookies": [
                    {"name": "cf_clearance", "value": "tok", "domain": ".hltv.org", "expires": -1},
                    {"name": "__cf_bm", "value": "bm", "domain": ".hltv.org", "expires": -1},
                ]
            }
        elif method == "Page.captureScreenshot":
            result = {"data": ""}
        else:
            result = {}
        return json.dumps({"id": msg_id, "result": result})

    def close(self):
        pass


def test_fetch_creates_tab_when_missing(monkeypatch):
    calls = []

    def urlopen(req, timeout=None):
        url = getattr(req, "full_url", None) or req.get_full_url()
        calls.append((req.get_method(), url))
        if url.endswith("/json/list"):
            if any(m == "PUT" or (m == "GET" and "json/new" in u) for m, u in calls[:-1]):
                body = json.dumps(
                    [
                        {
                            "type": "page",
                            "url": "https://www.hltv.org/matches",
                            "title": "Matches",
                            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1",
                        }
                    ]
                )
            else:
                body = "[]"
            return _Resp(body)
        if "json/new" in url:
            return _Resp("{}")
        raise AssertionError(url)

    monkeypatch.setattr("hltv_bot.cdp.urlopen", urlopen)
    monkeypatch.setattr("hltv_bot.cdp._connect_ws", lambda *a, **k: _CdpWs(_Ws([])))
    slept = []
    snap = fetch_keeper_snapshot("http://127.0.0.1:9222", sleep=slept.append)
    assert snap.created_new_tab is True
    assert snap.title == "Matches"
    assert any(c["name"] == "cf_clearance" for c in snap.cookies)
    assert snap.screenshot_png is None
    assert slept == [2.0]


def test_tcp_refused(monkeypatch):
    def boom(req, timeout=None):
        raise URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr("hltv_bot.cdp.urlopen", boom)
    with pytest.raises(CdpUnavailable):
        fetch_keeper_snapshot("http://127.0.0.1:9222")


def test_challenge_takes_screenshot(monkeypatch):
    def urlopen(req, timeout=None):
        body = json.dumps(
            [
                {
                    "type": "page",
                    "url": "https://www.hltv.org/matches",
                    "title": "Just a moment...",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/1",
                }
            ]
        )
        return _Resp(body)

    class ChallengeWs(_Ws):
        def recv(self):
            payload = json.loads(self.sent[-1])
            msg_id = payload["id"]
            method = payload["method"]
            if method == "Runtime.evaluate":
                result = {"result": {"value": "Just a moment..."}}
            elif method == "Network.getAllCookies":
                result = {"cookies": [{"name": "__cf_bm", "value": "x", "domain": ".hltv.org"}]}
            elif method == "Page.captureScreenshot":
                result = {"data": "aGVsbG8="}
            else:
                result = {}
            return json.dumps({"id": msg_id, "result": result})

    monkeypatch.setattr("hltv_bot.cdp.urlopen", urlopen)
    monkeypatch.setattr("hltv_bot.cdp._connect_ws", lambda *a, **k: _CdpWs(ChallengeWs([])))
    snap = fetch_keeper_snapshot()
    assert snap.screenshot_png == b"hello"
    assert snap.title == "Just a moment..."


def test_close_extra_pages_drops_unrelated_matches_and_keeps_keeper(monkeypatch):
    from hltv_bot.cdp import close_extra_pages

    closed = []

    def fake_list(base, timeout):
        return [
            {"type": "page", "id": "t1", "url": "https://www.hltv.org/matches"},
            {"type": "page", "id": "t2", "url": "https://www.hltv.org/matches/2398102/vitality-vs-furia"},
            {"type": "page", "id": "t3", "url": "https://www.hltv.org/matches/2398088/mouz-vs-nrg"},
            {"type": "other", "id": "t4", "url": "chrome://omnibox-popup.top-chrome/"},
        ]

    def fake_http(method, url, timeout):
        closed.append(url)
        return {}

    monkeypatch.setattr("hltv_bot.cdp._list_pages", fake_list)
    monkeypatch.setattr("hltv_bot.cdp._http_json", fake_http)
    monkeypatch.setattr("hltv_bot.cdp.vnc_up", lambda: False)

    n = close_extra_pages(
        "http://127.0.0.1:9222",
        keep_urls=["https://www.hltv.org/matches/2398102/vitality-vs-furia"],
    )
    assert n == 1
    assert closed == ["http://127.0.0.1:9222/json/close/t3"]

