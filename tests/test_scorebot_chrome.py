from hltv_bot.scorebot_chrome import (
    _SCOREBOT_JS,
    _pick_match_page,
    chrome_scorebot_enabled,
    scorebot_js,
)


def test_js_is_page_ws_not_python_upgrade():
    assert "new WebSocket" in _SCOREBOT_JS
    assert "readyForMatch" in _SCOREBOT_JS
    assert "transport=websocket" in _SCOREBOT_JS
    assert "transport=polling" not in _SCOREBOT_JS
    assert 'sock.send("2probe")' not in _SCOREBOT_JS
    assert 'ws.send("40")' in _SCOREBOT_JS
    assert "curl_cffi" not in _SCOREBOT_JS


def test_js_reconnects_and_logs_close_code():
    assert "scheduleReconnect" in _SCOREBOT_JS
    assert "ev.code" in _SCOREBOT_JS
    assert "ws ping timeout" in _SCOREBOT_JS
    assert "handshake()" in _SCOREBOT_JS
    assert "pingInterval" in _SCOREBOT_JS
    assert "let pingTimeout = 60000" in _SCOREBOT_JS
    assert "ws ping n=" in _SCOREBOT_JS
    assert "readyForMatch listId=" in _SCOREBOT_JS
    assert "ws non-text" in _SCOREBOT_JS
    assert 'detail: "ws close"' not in _SCOREBOT_JS
    assert "setTimeout(flush, 0)" in _SCOREBOT_JS
    assert "const wait = 3" in _SCOREBOT_JS
    assert 't === "2probe"' in _SCOREBOT_JS
    assert "TextDecoder" in _SCOREBOT_JS
    assert _SCOREBOT_JS.index("armPing();") < _SCOREBOT_JS.index('if (t === "3probe")')
    assert "if (readySent) return" in _SCOREBOT_JS
    assert "JSON.parse(JSON.stringify(payload))" in _SCOREBOT_JS
    assert "board r=" in _SCOREBOT_JS


def test_pick_match_page_skips_keeper_list():
    pages = [
        {"type": "page", "url": "https://www.hltv.org/matches", "id": "a"},
        {
            "type": "page",
            "url": "https://www.hltv.org/matches/2396932/faze-vs-navi",
            "id": "b",
            "webSocketDebuggerUrl": "ws://x",
        },
    ]
    got = _pick_match_page(pages, "https://www.hltv.org/matches/2396932/faze-vs-navi", "2396932")
    assert got is not None
    assert got["id"] == "b"


def test_pick_match_page_does_not_pick_unrelated_match():
    pages = [
        {"type": "page", "url": "https://www.hltv.org/matches/2398088/mouz-vs-nrg", "id": "mouz"},
        {"type": "page", "url": "https://www.hltv.org/matches", "id": "list"},
    ]
    # Looking for match 2398102 must NOT return mouz
    got = _pick_match_page(pages, "https://www.hltv.org/matches/2398102/x", "2398102")
    assert got is None



def test_scorebot_env_curl_disables_chrome(monkeypatch):
    monkeypatch.setenv("HLTV_SCOREBOT", "curl")
    assert chrome_scorebot_enabled() is False


def test_scorebot_js_keeps_modulo_and_injects_ids():
    js = scorebot_js("2398088", "https://scorebot-lb.hltv.org/")
    assert '"2398088"' in js
    assert '"https://scorebot-lb.hltv.org"' in js
    assert "pingCount % 10" in js
    assert "__LIST_ID__" not in js
    assert "__HTTP_BASE__" not in js
    assert "%s" not in js


def test_iter_scorebot_tries_chrome_first():
    src = open("hltv_bot/scorebot.py", encoding="utf-8").read()
    assert "chrome_scorebot_enabled" in src
    assert "iter_scorebot_chrome" in src
    assert src.find("iter_scorebot_chrome") < src.find("from curl_cffi.requests import Session")
