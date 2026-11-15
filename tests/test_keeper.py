import threading
from hltv_bot.bot import DEFAULT_ADMIN_ID, HltvTelegramBot
from hltv_bot.cdp import CdpSnapshot, CdpUnavailable
from hltv_bot.keeper import ADMIN_CHALLENGE_EVERY, tick_keeper
from hltv_bot.session import BrowserSession


class FakeTg:
    def __init__(self):
        self.sent = []
        self.photos = []
        self.deleted = []

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text, "msg"))
        return {"message_id": 10 + len(self.sent)}

    def send_photo(self, chat_id, photo_bytes, caption="", filename="cf-challenge.png"):
        self.photos.append((chat_id, photo_bytes, caption, filename))
        return {"message_id": 900 + len(self.photos)}

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def _bot(tmp_path):
    p = tmp_path / "session.json"
    p.write_text('{"impersonate":"chrome131","user_agent":"UA","cookie":"cf_clearance=good; __cf_bm=old"}\n')
    sess = BrowserSession("chrome131", {}, "cf_clearance=good; __cf_bm=old", path=p)
    tg = FakeTg()
    bot = HltvTelegramBot(tg, sess, admin_ids={DEFAULT_ADMIN_ID}, cdp_url="http://127.0.0.1:9222")
    return bot, tg, p


def test_challenge_alerts_photo_not_deleted(tmp_path, monkeypatch):
    bot, tg, p = _bot(tmp_path)
    snap = CdpSnapshot(
        title="Just a moment...",
        url="https://www.hltv.org/matches",
        cookies=[{"name": "__cf_bm", "value": "x", "domain": ".hltv.org"}],
        screenshot_png=b"png",
    )
    monkeypatch.setattr("hltv_bot.keeper.fetch_keeper_snapshot", lambda *a, **k: snap)
    tick_keeper(bot, sleep=lambda s: None)
    assert tg.photos
    assert all(mid < 900 or mid not in tg.deleted for mid in [900, 901])
    photo_ids = [900 + i for i in range(len(tg.photos))]
    assert not (set(photo_ids) & set(tg.deleted))
    assert "cf_clearance=good" in p.read_text(encoding="utf-8")
    assert "challenge" in tg.sent[0][1].lower() or "challenge" in tg.photos[0][2].lower()


def test_cdp_down_does_not_raise(tmp_path, monkeypatch):
    bot, tg, p = _bot(tmp_path)

    def boom(*a, **k):
        raise CdpUnavailable("refused")

    monkeypatch.setattr("hltv_bot.keeper.fetch_keeper_snapshot", boom)
    from hltv_bot.keeper import _loop

    bot.export_every = 60
    bot._keeper_stop = threading.Event()

    def stop_soon(*a, **k):
        bot._keeper_stop.set()
        return True

    monkeypatch.setattr(bot._keeper_stop, "wait", stop_soon)
    _loop(bot)
    assert bot.keeper_cdp == "down"
    assert any("cdp down" in t[1] for t in tg.sent)


def test_healthy_overlay_and_restored(tmp_path, monkeypatch):
    bot, tg, p = _bot(tmp_path)
    bot._was_challenge = True
    snap = CdpSnapshot(
        title="Matches",
        url="https://www.hltv.org/matches",
        cookies=[
            {"name": "cf_clearance", "value": "newcf", "domain": ".hltv.org", "expires": -1},
            {"name": "__cf_bm", "value": "newbm", "domain": ".hltv.org", "expires": -1},
        ],
        screenshot_png=None,
    )
    monkeypatch.setattr("hltv_bot.keeper.fetch_keeper_snapshot", lambda *a, **k: snap)
    monkeypatch.setattr("hltv_bot.keeper.close_extra_pages", lambda *a, **k: None)
    tick_keeper(bot, sleep=lambda s: None)
    assert "cf_clearance=newcf" in bot.session.cookie
    assert any("restored" in t[1] for t in tg.sent)


def test_challenge_interval_constant():
    assert ADMIN_CHALLENGE_EVERY >= 300
