from hltv_bot.bot import HltvTelegramBot, WatchState
from hltv_bot.session import BrowserSession
from hltv_bot.telegram_api import is_not_modified


class _Tg:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.fail_edit = False

    def send_rich(self, chat_id, html, **kwargs):
        self.sent.append(html)
        return {"message_id": 10 + len(self.sent)}

    def send_message(self, chat_id, text):
        return self.send_rich(chat_id, text)

    def edit_rich(self, chat_id, message_id, html, **kwargs):
        if self.fail_edit:
            raise RuntimeError("Bad Request: message is not modified")
        self.edited.append((message_id, html))
        return {"message_id": message_id}


def _bot():
    return HltvTelegramBot(
        _Tg(),
        BrowserSession("chrome131", {}, "", path=None),
        admin_ids={1},
    )


def test_flush_edits_in_place_never_sends():
    bot = _bot()
    st = WatchState(chat_id=1, list_id="1", meta={}, message_id=7, sent_html="old")
    bot._flush_watch(st, "<table bordered compact><caption>LIVE</caption></table>")
    assert bot.tg.edited
    assert bot.tg.sent == []
    assert st.message_id == 7
    assert st.pending is False


def test_flush_not_modified_does_not_resend():
    bot = _bot()
    bot.tg.fail_edit = True
    st = WatchState(chat_id=1, list_id="1", meta={}, message_id=7, sent_html="old")
    bot._flush_watch(st, "<p>x</p>")
    assert bot.tg.sent == []
    assert st.message_id == 7
    assert is_not_modified(RuntimeError("message is not modified"))


def test_flush_without_message_id_does_not_send():
    bot = _bot()
    st = WatchState(chat_id=1, list_id="1", meta={}, message_id=None)
    bot._flush_watch(st, "<p>x</p>")
    assert bot.tg.sent == []


def test_bump_is_the_only_new_send():
    bot = _bot()
    st = WatchState(chat_id=1, list_id="1", meta={}, message_id=7, text="<p>x</p>")
    bot.watch = st
    bot._flush_watch(st, st.text, send_new=True)
    assert len(bot.tg.sent) == 1
    assert st.message_id != 7
