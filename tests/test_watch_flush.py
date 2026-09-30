"""Command replies still auto-delete. Live watch cards live on archive/chrome-full."""

from hltv_bot.bot import HltvTelegramBot, MSG_TTL
from hltv_bot.session import BrowserSession


class Tg:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self.edited = []

    def send_message(self, chat_id, text, silent=False):
        self.sent.append((chat_id, text, silent))
        return {"message_id": 7}

    def send_photo(self, chat_id, photo, caption="", filename="hltv.png", silent=False):
        self.sent.append((chat_id, caption, silent))
        return {"message_id": 7}

    def edit_message_media(self, chat_id, message_id, photo, caption="", filename="hltv.png"):
        self.edited.append((chat_id, message_id, caption))
        return {"message_id": message_id}

    def edit_message(self, chat_id, message_id, text):
        self.edited.append((chat_id, message_id, text))
        return {"message_id": message_id}

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def test_command_reply_is_scheduled_for_delete(monkeypatch):
    tg = Tg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "cf_clearance=x"), admin_ids={1})
    bot.msg_ttl = MSG_TTL
    scheduled = {}

    def fake_timer(delay, fn):
        scheduled["delay"] = delay
        scheduled["fn"] = fn

        class T:
            def start(self):
                return None

        return T()

    monkeypatch.setattr("hltv_bot.bot.threading.Timer", fake_timer)
    bot.handle_text(1, "/hltv", user_id=1, message_id=3)
    assert scheduled["delay"] == MSG_TTL
    assert tg.sent
    assert tg.sent[0][2] is False


def test_score_push_stays_in_the_chat_that_enabled_it_and_replaces_the_previous(tmp_path, monkeypatch):
    from hltv_bot.reminders import Notice

    tg = Tg()
    seq = {"n": 20}

    def send_photo(chat_id, photo, caption="", filename="hltv.png", silent=False):
        seq["n"] += 1
        tg.sent.append((chat_id, caption, silent))
        return {"message_id": seq["n"]}

    tg.send_photo = send_photo
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: [-200, -100])
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    bot = HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={1},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot.handle_text(-100, "/watch", user_id=1)
    tg.sent.clear()
    tg.deleted.clear()
    first = Notice("m:9:score:12-9|bo3", "<b>比分</b>", {"view": "match"}, "9", "multi")
    bot._broadcast(first)
    assert [item[0] for item in tg.sent] == [-100]
    second = Notice("m:9:score:12-10|bo3", "<b>比分</b>", {"view": "match"}, "9", "multi")
    bot._broadcast(second)
    assert tg.deleted == []
    assert tg.edited == [(-100, 21, "<b>比分</b>")]
    assert [item[0] for item in tg.sent] == [-100]
    single = Notice("m:9:score:12-11|bo3", "<b>比分</b>", {"view": "match"}, "9", "single")
    tg.sent.clear()
    bot._broadcast(single)
    assert tg.sent == []


def test_events_list_and_daily_digest_are_not_deleted(monkeypatch):
    from hltv_bot.reminders import Notice

    tg = Tg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "cf_clearance=x"), admin_ids={1})
    timers: list = []

    def fake_timer(*args, **kwargs):
        timers.append(args)

        class T:
            def start(self):
                return None

        return T()

    monkeypatch.setattr("hltv_bot.bot.threading.Timer", fake_timer)
    monkeypatch.setattr("hltv_bot.bot.fetch_events", lambda sess: [{"id": "1", "name": "BLAST", "tier": "T1"}])
    monkeypatch.setattr("hltv_bot.bot.filter_and_sort_events", lambda rows, allowed_tiers=(): rows)
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    bot.handle_text(1, "/events", user_id=1, message_id=9)
    bot.handle_text(1, "/status", user_id=2, message_id=4)
    assert [item[0] for item in timers] == [MSG_TTL, MSG_TTL, MSG_TTL]
    for item in timers:
        item[1]()
    assert tg.deleted == [9, 4, 7]
    timers.clear()
    tg.deleted.clear()
    assert tg.sent

    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: [5])
    bot._broadcast(Notice("d:2026-09-27:10", "<b>赛程</b>", {"view": "matches", "rows": []}))
    assert timers == []
    sent_ids = [item[0] for item in tg.sent]
    assert 5 in sent_ids
    assert 1 in sent_ids

    tg.sent.clear()
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: [])
    bot._broadcast(Notice("d:2026-09-27:20", "<b>赛程</b>", None))
    assert [item[0] for item in tg.sent] == [1]
