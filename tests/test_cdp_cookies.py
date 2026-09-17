import inspect
import json

from hltv_bot.session import (
    COOKIE_QUIET_AFTER_PASTE,
    BrowserSession,
    is_challenge_cdp,
    merge_cdp_cookies,
    save_cookie,
)


EXISTING = (
    "io=live; _cfuvid=uvid1; __cflb=lb1; cf_clearance=oldcf; __cf_bm=oldbm; "
    "OptanonConsent=datestamp=x; MatchFilter=keep"
)


def _c(name, value, domain=".hltv.org", **extra):
    row = {"name": name, "value": value, "domain": domain}
    row.update(extra)
    return row


def test_merge_healthy_example():
    cdp = [
        _c("cf_clearance", "newcf"),
        _c("__cf_bm", "newbm"),
        _c("io", "sid9", domain="scorebot-lb.hltv.org"),
        _c("OptanonConsent", "datestamp=y"),
        _c("NID", "xyz", domain=".google.com"),
        _c("__cflb", "bad\n"),
        _c("cf_clearance", "part", partitionKey={"topLevelSite": "https://hltv.org"}),
    ]
    out = merge_cdp_cookies(EXISTING, cdp)
    assert "io=live" in out
    assert "sid9" not in out
    assert "cf_clearance=newcf" in out
    assert "__cf_bm=newbm" in out
    assert "OptanonConsent=datestamp=y" in out
    assert "MatchFilter=keep" in out
    assert "NID" not in out
    assert "part" not in out
    assert "\n" not in out
    assert out.startswith("io=live; _cfuvid=uvid1; __cflb=lb1; cf_clearance=newcf; __cf_bm=newbm")


def test_cdp_io_does_not_clobber_live_sid():
    out = merge_cdp_cookies("io=live; cf_clearance=x", [_c("io", "sid9", domain="scorebot-lb.hltv.org")])
    assert "io=live" in out
    assert "sid9" not in out


def test_expired_cdp_row_does_not_overlay():
    now = 1_700_000_000.0
    cdp = [_c("cf_clearance", "expired", expires=now - 10)]
    out = merge_cdp_cookies("cf_clearance=good; __cf_bm=bm", cdp, now=now)
    assert "cf_clearance=good" in out
    assert is_challenge_cdp("Matches", "https://www.hltv.org/matches", cdp, now=now)


def test_session_cookie_expires_minus_one_usable():
    cdp = [_c("cf_clearance", "sess", expires=-1), _c("__cf_bm", "bm", expires=-1)]
    assert not is_challenge_cdp("Matches", "https://www.hltv.org/matches", cdp)
    out = merge_cdp_cookies("cf_clearance=old", cdp)
    assert "cf_clearance=sess" in out


def test_empty_cdp_keeps_header():
    assert merge_cdp_cookies(EXISTING, []) == EXISTING


def test_title_and_missing_clearance_are_challenge():
    assert is_challenge_cdp("Just a moment...", "https://www.hltv.org/matches", [_c("__cf_bm", "x")])
    assert is_challenge_cdp("Matches", "https://challenges.cloudflare.com/turnstile", [_c("cf_clearance", "x")])
    good = [_c("cf_clearance", "x"), _c("__cf_bm", "y")]
    assert not is_challenge_cdp("Matches", "https://www.hltv.org/matches", good)


def test_save_cookie_atomic_and_keeps_ua(tmp_path):
    p = tmp_path / "session.json"
    p.write_text(
        '{"impersonate":"chrome131","user_agent":"UA","sec_ch_ua":"C","cookie":"cf_clearance=a"}\n',
        encoding="utf-8",
    )
    save_cookie(p, "cf_clearance=b; __cf_bm=z")
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["user_agent"] == "UA"
    assert data["impersonate"] == "chrome131"
    assert data["sec_ch_ua"] == "C"
    assert "cf_clearance=b" in data["cookie"]
    leftovers = list(tmp_path.glob(".session.json.*.tmp"))
    assert leftovers == []


def test_overlay_does_not_call_apply_cookie_str():
    src = inspect.getsource(BrowserSession.overlay_cdp)
    assert "self.apply_cookie_str(" not in src
    assert "_apply_cookie_str_unlocked" in src


def test_overlay_skips_challenge_and_keeps_object(tmp_path):
    p = tmp_path / "session.json"
    p.write_text('{"impersonate":"chrome131","user_agent":"UA","cookie":"cf_clearance=good; __cf_bm=old"}\n')
    sess = BrowserSession("chrome131", {"cookie": "cf_clearance=good; __cf_bm=old"}, "cf_clearance=good; __cf_bm=old", path=p)
    oid = id(sess)
    cdp = [_c("__cf_bm", "from-turnstile")]
    assert is_challenge_cdp("Just a moment...", "https://www.hltv.org/matches", cdp)
    # keeper must not overlay when challenge
    assert id(sess) == oid
    assert sess.cookie == "cf_clearance=good; __cf_bm=old"


def test_quiet_blocks_healthy_overlay(tmp_path):
    p = tmp_path / "session.json"
    p.write_text('{"impersonate":"chrome131","user_agent":"UA","cookie":"cf_clearance=a"}\n')
    sess = BrowserSession("chrome131", {}, "cf_clearance=a", path=p)
    sess.apply_paste("Cookie: cf_clearance=paste; __cf_bm=pbm")
    assert COOKIE_QUIET_AFTER_PASTE >= 60
    assert sess.overlay_cdp([_c("cf_clearance", "cdp"), _c("__cf_bm", "cdpbm")]) is False
    assert "cf_clearance=paste" in sess.cookie
    assert "__cf_bm=pbm" in p.read_text(encoding="utf-8")


def test_paste_wins_vs_prior_healthy_overlay(tmp_path):
    p = tmp_path / "session.json"
    p.write_text('{"impersonate":"chrome131","user_agent":"UA","cookie":"cf_clearance=old"}\n')
    sess = BrowserSession("chrome131", {}, "cf_clearance=old", path=p)
    sess.overlay_cdp([_c("cf_clearance", "fromcdp"), _c("__cf_bm", "cdpbm")])
    sess.apply_paste("Cookie: cf_clearance=paste; __cf_bm=pbm")
    text = p.read_text(encoding="utf-8")
    assert "cf_clearance=paste" in text
    assert "fromcdp" not in sess.cookie
    assert id(sess) == id(sess)


def test_cli_write_refuses_challenge(tmp_path, monkeypatch):
    from hltv_bot import __main__ as mainmod
    from hltv_bot.cdp import CdpSnapshot

    p = tmp_path / "session.json"
    p.write_text('{"impersonate":"chrome131","user_agent":"UA","cookie":"cf_clearance=good"}\n')
    snap = CdpSnapshot(
        title="Just a moment...",
        url="https://www.hltv.org/matches",
        cookies=[_c("__cf_bm", "x")],
        screenshot_png=None,
    )
    monkeypatch.setattr("hltv_bot.cdp.fetch_keeper_snapshot", lambda *a, **k: snap)
    rc = mainmod.main(["export-cookies", "--write", "-s", str(p)])
    assert rc == 1
    assert "cf_clearance=good" in p.read_text(encoding="utf-8")
