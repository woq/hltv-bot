"""Outbound delay policy. Run on every commit/push (see AGENTS.md)."""

from pathlib import Path

from hltv_bot.bot import (
    ADMIN_WS_FAIL_EVERY,
    ADMIN_WS_FAIL_MIN,
    CMD_COOLDOWN,
    DEFAULT_CMD_COOLDOWN,
    GET_UPDATES_FAIL_SLEEP,
    MIN_EDIT_INTERVAL,
    MSG_TTL,
    TG_COMMANDS_GAP,
)
from hltv_bot.http import HTML_MIN_GAP
from hltv_bot.matches import MATCH_CACHE_TTL
from hltv_bot.scorebot import (
    POLL_5XX_GAP,
    POLL_EMPTY_GAP,
    POLL_MIN_GAP,
    RECONNECT_5XX,
    RECONNECT_MAX,
    RECONNECT_MIN,
    WS_ATTEMPT_GAP,
    WS_RETRY_EVERY,
)
from hltv_bot.telegram_api import TG_RETRY_AFTER_CAP, retry_after_seconds

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "hltv_bot"


def _src(name: str) -> str:
    return (PKG / name).read_text(encoding="utf-8")


def test_delay_floors():
    assert HTML_MIN_GAP >= 3.0
    assert MATCH_CACHE_TTL >= 45.0
    assert POLL_MIN_GAP >= 5.0
    assert POLL_EMPTY_GAP >= 20.0
    assert POLL_5XX_GAP >= 30.0
    assert RECONNECT_MIN >= 15.0
    assert RECONNECT_5XX >= 25.0
    assert RECONNECT_MAX >= 180.0
    assert WS_RETRY_EVERY >= 15.0
    assert WS_ATTEMPT_GAP >= 1.0
    assert MIN_EDIT_INTERVAL >= 1.8
    assert MSG_TTL >= 30.0
    assert GET_UPDATES_FAIL_SLEEP >= 3.0
    assert TG_COMMANDS_GAP >= 0.3
    assert TG_RETRY_AFTER_CAP >= 15.0
    assert ADMIN_WS_FAIL_MIN >= 2
    assert ADMIN_WS_FAIL_EVERY >= 300.0
    assert CMD_COOLDOWN["/matches"] >= 8.0
    assert CMD_COOLDOWN["/watch"] >= 6.0
    assert CMD_COOLDOWN["/bump"] >= 4.0
    assert DEFAULT_CMD_COOLDOWN >= 1.2


def test_html_only_goes_through_gapped_request():
    http = _src("http.py")
    assert "_HTML_GAP.sleep(HTML_MIN_GAP)" in http
    matches = _src("matches.py")
    assert "from hltv_bot.http import request" in matches
    assert "curl_cffi" not in matches
    assert "urlopen" not in matches


def test_curl_cffi_only_in_http_and_scorebot():
    for path in PKG.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "curl_cffi" in text:
            assert path.name in {"http.py", "scorebot.py", "profile.py"}, path.name


def test_scorebot_sleeps_on_poll_reconnect_ws_and_handshake():
    src = _src("scorebot.py")
    assert "gap = poll_gap(" in src
    assert "time.sleep(gap)" in src
    assert "wait = reconnect_wait(" in src
    assert "time.sleep(wait)" in src
    assert "time.sleep(RECONNECT_MIN)" in src
    assert "next_ws = now + ws_retry_every" in src
    assert "time.sleep(WS_ATTEMPT_GAP)" in src
    assert "if ws_upgrade_refused(last):" in src


def test_bot_edit_cmd_getupdates_and_setcommands_gaps():
    src = _src("bot.py")
    assert "wait < MIN_EDIT_INTERVAL" in src
    assert "time.sleep(GET_UPDATES_FAIL_SLEEP)" in src
    assert "self._cool.allow(key, interval)" in src
    assert "time.sleep(TG_COMMANDS_GAP)" in src
    assert "ADMIN_WS_FAIL_EVERY" in src


def test_telegram_429_uses_retry_after_on_call_and_getupdates():
    src = _src("telegram_api.py")
    assert src.count("retry_after_seconds(") >= 2
    assert "def get_updates" in src
    assert 'e.code == 429' in src
    body = '{"parameters":{"retry_after":9}}'
    assert retry_after_seconds(body) == 9.0
    assert retry_after_seconds("not-json") == 3.0
    assert retry_after_seconds('{"parameters":{"retry_after":99}}') == TG_RETRY_AFTER_CAP


def test_urlopen_only_telegram_or_cli_probe():
    hits = []
    for path in PKG.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "urlopen" in text:
            hits.append(path.name)
    assert set(hits) <= {"telegram_api.py", "scorebot.py"}
    assert "def probe_scorebot" in _src("scorebot.py")
