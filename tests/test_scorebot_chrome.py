from hltv_bot.scorebot_chrome import (
    _SCOREBOT_JS,
    _pick_match_page,
    chrome_scorebot_enabled,
)


def test_js_is_page_ws_not_python_upgrade():
    assert "new WebSocket" in _SCOREBOT_JS
    assert "readyForMatch" in _SCOREBOT_JS
    assert "credentials: \"include\"" in _SCOREBOT_JS
    assert "curl_cffi" not in _SCOREBOT_JS


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


def test_scorebot_env_curl_disables_chrome(monkeypatch):
    monkeypatch.setenv("HLTV_SCOREBOT", "curl")
    assert chrome_scorebot_enabled() is False


def test_iter_scorebot_tries_chrome_first():
    src = open("hltv_bot/scorebot.py", encoding="utf-8").read()
    assert "chrome_scorebot_enabled" in src
    assert "iter_scorebot_chrome" in src
    assert src.find("iter_scorebot_chrome") < src.find("from curl_cffi.requests import Session")
