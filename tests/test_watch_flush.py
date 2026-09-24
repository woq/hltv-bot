"""Command replies still auto-delete. Live watch cards live on archive/chrome-full."""

from hltv_bot.bot import HltvTelegramBot, MSG_TTL
from hltv_bot.session import BrowserSession


class Tg:
    def __init__(self):
        self.sent = []
        self.deleted = []

    def send_message(self, chat_id, text, silent=False):
        self.sent.append((chat_id, text, silent))
        return {"message_id": 7}

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
    bot.handle_text(1, "/help", user_id=1, message_id=3)
    assert scheduled["delay"] == MSG_TTL
    assert tg.sent
    assert tg.sent[0][2] is False
