"""Outbound delay policy. Run on every commit/push (see AGENTS.md)."""

from pathlib import Path

from hltv_bot.bot import (
    CMD_COOLDOWN,
    DEFAULT_CMD_COOLDOWN,
    GET_UPDATES_FAIL_SLEEP,
    MSG_TTL,
    MATCH_PAGE_MAX,
    MATCH_PAGE_MIN,
    TG_COMMANDS_GAP,
)
from hltv_bot.watch import MAX_EDITS_PER_MINUTE, MIN_EDIT_INTERVAL as WATCH_MIN_EDIT
from hltv_bot.http import HTML_MIN_GAP
from hltv_bot.matches import MATCH_CACHE_TTL
from hltv_bot.keeper import ADMIN_CHALLENGE_EVERY, CDP_EXPORT_EVERY
from hltv_bot.scorebot import (
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
    assert RECONNECT_MIN >= 15.0
    assert RECONNECT_5XX >= 25.0
    assert RECONNECT_MAX >= 180.0
    assert WS_RETRY_EVERY >= 15.0
    assert WS_ATTEMPT_GAP >= 1.0
    assert WATCH_MIN_EDIT >= 3.0
    assert MAX_EDITS_PER_MINUTE == 19
    assert MAX_EDITS_PER_MINUTE < 20
    assert MSG_TTL >= 30.0
    assert GET_UPDATES_FAIL_SLEEP >= 3.0
    assert TG_COMMANDS_GAP >= 0.3
    assert MATCH_PAGE_MIN >= 3.0
    assert MATCH_PAGE_MAX <= 5.0
    assert MATCH_PAGE_MAX > MATCH_PAGE_MIN
    assert "self._rr % 2 == 1" in _src("bot.py")
    assert TG_RETRY_AFTER_CAP >= 15.0
    assert CMD_COOLDOWN["/matches"] >= 8.0
    assert CMD_COOLDOWN["/events"] >= 8.0
    assert DEFAULT_CMD_COOLDOWN >= 1.2
    assert CDP_EXPORT_EVERY >= 60.0
    assert ADMIN_CHALLENGE_EVERY >= 300.0


def test_html_only_goes_through_gapped_request():
    http = _src("http.py")
    assert "_HTML_GAP.sleep(HTML_MIN_GAP)" in http
    matches = _src("matches.py")
    assert "from hltv_bot.http import request" in matches
    assert "curl_cffi" not in matches
    assert "urlopen" not in matches
    events = _src("events.py")
    assert "from hltv_bot.http import request" in events
    assert "curl_cffi" not in events
    assert "urlopen" not in events


def test_curl_cffi_only_in_http_and_scorebot():
    for path in PKG.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "curl_cffi" in text:
            assert path.name in {"http.py", "scorebot.py", "profile.py"}, path.name


def test_scorebot_sleeps_on_reconnect_ws_and_handshake():
    src = _src("scorebot.py")
    assert "wait = reconnect_wait(" in src
    assert "time.sleep(wait)" in src
    assert "time.sleep(RECONNECT_MIN)" in src
    assert "time.sleep(WS_ATTEMPT_GAP)" in src
    assert "if ws_upgrade_refused(last):" in src


def test_bot_edit_cmd_getupdates_and_setcommands_gaps():
    src = _src("bot.py")
    assert "time.sleep(GET_UPDATES_FAIL_SLEEP)" in src
    assert "self._cool.allow(key, interval)" in src
    assert "time.sleep(TG_COMMANDS_GAP)" in src
    assert "disable_notification" not in src
    assert "silent=silent" in src
    assert "random.uniform(MATCH_PAGE_MIN, MATCH_PAGE_MAX)" in src
    assert "_events_loaded" in src


def test_telegram_429_uses_retry_after_on_call_and_getupdates():
    src = _src("telegram_api.py")
    assert src.count("retry_after_seconds(") >= 2
    assert "def get_updates" in src
    assert 'e.code == 429' in src
    assert "retry_429=False" in src
    assert "class TelegramRateLimit" in src
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
    assert set(hits) <= {"telegram_api.py", "scorebot.py", "cdp.py", "team_logos.py"}
    assert "def probe_scorebot" in _src("scorebot.py")


def test_cdp_and_keeper_do_not_use_curl_cffi():
    assert "curl_cffi" not in _src("cdp.py")
    assert "curl_cffi" not in _src("keeper.py")
    assert "curl_cffi" not in _src("scorebot_chrome.py")
    assert 'origin="http://127.0.0.1:9222"' in _src("cdp.py")
    assert "def fetch_via_chrome" in _src("cdp.py")
    assert "awaitPromise" in _src("cdp.py")
    assert "def _want_chrome" in _src("http.py")
    assert "close_extra_pages" in _src("cdp.py")


def test_deploy_does_not_start_chrome():
    wf = (ROOT / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    assert "systemctl restart hltv-bot" in wf
    assert "ssh-keyscan -p 2233" in wf
    assert 'SSH="ssh -p 2233' in wf
    assert "systemctl restart hltv-chrome" not in wf
    assert "systemctl enable hltv-chrome" not in wf
    assert "systemctl start hltv-chrome" not in wf
    assert "systemctl start xvfb@" not in wf
    chrome = (ROOT / "deploy/chrome-session/hltv-chrome.service").read_text(encoding="utf-8")
    assert "Restart=no" in chrome
    assert "Restart=always" not in chrome
    assert "--no-sandbox" in chrome
    bot_unit = (ROOT / "deploy/hltv-bot.service").read_text(encoding="utf-8")
    assert "Wants=hltv-chrome" not in bot_unit
    assert "Requires=hltv-chrome" not in bot_unit
