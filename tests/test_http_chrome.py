import os

from hltv_bot.bot import DEFAULT_ADMIN_ID, HltvTelegramBot
from hltv_bot.http import CloudflareError, _want_chrome, request
from hltv_bot.session import BrowserSession


def test_want_chrome_default_hltv_get():
    os.environ.pop("HLTV_HTTP", None)
    assert _want_chrome("GET", "https://www.hltv.org/matches")
    assert _want_chrome("GET", "https://hltv.org/matches/1/x")
    assert not _want_chrome("POST", "https://www.hltv.org/matches")
    assert not _want_chrome("GET", "https://scorebot-lb.hltv.org/socket.io/")


def test_want_chrome_off_via_env(monkeypatch):
    monkeypatch.setenv("HLTV_HTTP", "curl")
    assert not _want_chrome("GET", "https://www.hltv.org/matches")


def test_chrome_fetch_used_before_curl(monkeypatch):
    os.environ.pop("HLTV_HTTP", None)
    called = {}

    def fake_chrome(url, timeout=25.0):
        called["url"] = url
        return 200, b"<html>ok</html>", {"content-type": "text/html"}

    monkeypatch.setattr("hltv_bot.cdp.fetch_via_chrome", fake_chrome)
    sess = BrowserSession("chrome131", {}, "cf_clearance=x")
    st, body, _ = request(sess, "GET", "https://www.hltv.org/matches")
    assert st == 200
    assert body.startswith(b"<html>")
    assert called["url"] == "https://www.hltv.org/matches"


def test_chrome_challenge_html_raises(monkeypatch):
    os.environ.pop("HLTV_HTTP", None)
    monkeypatch.setattr(
        "hltv_bot.cdp.fetch_via_chrome",
        lambda url, timeout=25.0: (200, b"<title>Just a moment...</title>", {}),
    )
    sess = BrowserSession("chrome131", {}, "cf_clearance=x")
    try:
        request(sess, "GET", "https://www.hltv.org/matches")
        assert False, "expected CloudflareError"
    except CloudflareError:
        pass


def test_status_lists_chrome_and_vnc(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.cdp.vnc_up", lambda: False)
    monkeypatch.setattr("hltv_bot.cdp.chrome_cgroup_bytes", lambda: 500 * 1048576)
    p = tmp_path / "session.json"
    p.write_text('{"impersonate":"chrome131","user_agent":"UA","cookie":"cf_clearance=tok"}\n')
    sess = BrowserSession("chrome131", {}, "cf_clearance=tok", path=p)
    sent = []

    class Tg:
        def send_message(self, chat_id, text):
            sent.append(text)
            return {"message_id": 1}

        def delete_message(self, chat_id, message_id):
            pass

    bot = HltvTelegramBot(Tg(), sess, admin_ids={DEFAULT_ADMIN_ID}, cdp_url="http://127.0.0.1:9222")
    bot.keeper_cdp = "up"
    bot.keeper_title = "HLTV Matches"
    bot.keeper_clearance = True
    bot.keeper_exported_at = 1.0
    bot._cmd_status(DEFAULT_ADMIN_ID)
    blob = sent[0]
    assert "chrome" in blob.lower()
    assert "vnc" in blob.lower()
    assert "http" in blob.lower()
    assert "500M" in blob or "500" in blob
