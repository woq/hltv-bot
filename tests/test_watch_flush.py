from hltv_bot.bot import HltvTelegramBot, WatchCard, WatchState, watch_debug_mode
from hltv_bot.session import BrowserSession
from hltv_bot.telegram_api import is_not_modified


class _Tg:
    def __init__(self):
        self.sent = []
        self.edited = []
        self.deleted = []
        self.fail_edit = False

    def send_rich(self, chat_id, html, **kwargs):
        self.sent.append((chat_id, html))
        return {"message_id": 10 + len(self.sent)}

    def send_message(self, chat_id, text):
        return self.send_rich(chat_id, text)

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    def edit_rich(self, chat_id, message_id, html, **kwargs):
        if self.fail_edit:
            raise RuntimeError("Bad Request: message is not modified")
        self.edited.append((chat_id, message_id, html))
        return {"message_id": message_id}


def _bot():
    return HltvTelegramBot(
        _Tg(),
        BrowserSession("chrome131", {}, "", path=None),
        admin_ids={1},
    )


def _state(**kwargs):
    cards = kwargs.pop("cards", None)
    st = WatchState(list_id="1", meta={}, **kwargs)
    if cards is not None:
        st.cards = cards
    return st


def test_non_watch_messages_auto_delete():
    import time

    bot = _bot()
    bot.msg_ttl = 0.05
    bot.handle_text(1, "/help", user_id=1, message_id=50)
    time.sleep(0.2)
    assert (1, 50) in bot.tg.deleted
    assert bot.tg.deleted  # bot reply too


def test_watch_user_command_is_kept(monkeypatch):
    scheduled: list[tuple[int, int]] = []
    bot = _bot()
    bot.msg_ttl = 30
    bot._schedule_delete = lambda c, m: scheduled.append((c, m))  # type: ignore[method-assign]
    bot.handle_text(1, "/help", user_id=1, message_id=50)
    assert (1, 50) in scheduled
    scheduled.clear()
    monkeypatch.setattr(
        "hltv_bot.bot.fetch_match_meta",
        lambda sess, raw: {"scorebotId": "9", "team1": "A", "team2": "B", "url": "https://x"},
    )
    monkeypatch.setattr("hltv_bot.bot.iter_scorebot", lambda *a, **k: iter(()))
    monkeypatch.setattr("hltv_bot.bot.scorebot_base", lambda url: "https://scorebot")
    bot.handle_text(1, "/watch 9", user_id=1, message_id=77)
    assert (1, 77) not in scheduled


def test_flush_edits_in_place_never_sends():
    bot = _bot()
    st = _state(cards={1: WatchCard(chat_id=1, message_id=7, sent_html="old")})
    bot._flush_watch(st, "<table bordered compact><caption>LIVE</caption></table>")
    assert bot.tg.edited
    assert bot.tg.sent == []
    assert st.cards[1].message_id == 7
    assert st.pending is False


def test_flush_edits_every_card():
    bot = _bot()
    st = _state(
        cards={
            1: WatchCard(chat_id=1, message_id=7, sent_html="old"),
            2: WatchCard(chat_id=2, message_id=8, sent_html="old"),
        }
    )
    bot._flush_watch(st, "<p>x</p>")
    assert [(c, m) for c, m, _ in bot.tg.edited] == [(1, 7), (2, 8)]
    assert bot.tg.sent == []
    assert st.cards[1].sent_html == "<p>x</p>"
    assert st.cards[2].sent_html == "<p>x</p>"


def test_flush_not_modified_does_not_resend():
    bot = _bot()
    bot.tg.fail_edit = True
    st = _state(cards={1: WatchCard(chat_id=1, message_id=7, sent_html="old")})
    bot._flush_watch(st, "<p>x</p>")
    assert bot.tg.sent == []
    assert st.cards[1].message_id == 7
    assert is_not_modified(RuntimeError("message is not modified"))


def test_flush_without_message_id_does_not_send():
    bot = _bot()
    st = _state(cards={1: WatchCard(chat_id=1, message_id=None)})
    bot._flush_watch(st, "<p>x</p>")
    assert bot.tg.sent == []


def test_bump_is_the_only_new_send():
    bot = _bot()
    st = _state(
        text="<p>x</p>",
        cards={1: WatchCard(chat_id=1, message_id=7)},
    )
    bot.watch = st
    bot._flush_watch(st, st.text, send_new=True, chat_id=1)
    assert len(bot.tg.sent) == 1
    assert st.cards[1].message_id != 7
    assert bot.tg.sent[0][0] == 1


def test_watch_debug_mode_healthy_vs_down():
    now = 1000.0
    assert watch_debug_mode("connecting", has_board=False, last_data_at=0, now=now)
    assert watch_debug_mode("reconnect", has_board=True, last_data_at=now, now=now)
    assert watch_debug_mode("connected", has_board=False, last_data_at=0, now=now)
    assert watch_debug_mode("connected", has_board=True, last_data_at=0, now=now)
    assert watch_debug_mode("connected", has_board=True, last_data_at=now - 90, now=now)
    assert not watch_debug_mode("connected", has_board=True, last_data_at=now - 5, now=now)
    assert not watch_debug_mode("idle", has_board=True, last_data_at=now - 5, now=now)


def test_watch_sends_only_command_chat(tmp_path, monkeypatch):
    import os

    from hltv_bot.chats import add_group

    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        (tmp_path / "data").mkdir()
        add_group(-100, "A")
        add_group(-200, "B")
        monkeypatch.setattr(
            "hltv_bot.bot.fetch_match_meta",
            lambda sess, raw: {
                "scorebotId": "9",
                "team1": "G2",
                "team2": "NaVi",
                "url": "https://x",
            },
        )
        monkeypatch.setattr("hltv_bot.bot.iter_scorebot", lambda *a, **k: iter(()))
        monkeypatch.setattr("hltv_bot.bot.scorebot_base", lambda url: "https://scorebot")
        bot = HltvTelegramBot(
            _Tg(),
            BrowserSession("chrome131", {}, "", path=None),
            admin_ids={1, 2},
        )
        bot.handle_text(-100, "/watch 9", user_id=1, chat_type="supergroup")
        chats = [c for c, _ in bot.tg.sent]
        assert -100 in chats
        assert -200 not in chats
        assert bot.watch is not None
        assert list(bot.watch.cards) == [-100]
        bot.handle_text(-200, "/watch", user_id=2, chat_type="supergroup")
        assert -200 in bot.watch.cards
        bot.handle_text(-200, "/stop", user_id=2, chat_type="supergroup")
        assert -200 not in bot.watch.cards
        assert -100 in bot.watch.cards
        bot.handle_text(-100, "/stop all", user_id=1, chat_type="supergroup")
        assert bot.watch is None
    finally:
        os.chdir(old)


def test_mark_watch_down_edits_debug_card():
    bot = _bot()
    st = _state(
        cards={1: WatchCard(chat_id=1, message_id=7, sent_html="old")},
        trace=["12:00:01 handshake HTTP 502"],
    )
    st.notice = "HTTP 502"
    st.meta = {"team1": "G2", "team2": "Spirit"}
    bot._mark_watch_down(st, "reconnect")
    assert bot.tg.edited
    html = bot.tg.edited[-1][2]
    assert "DEBUG" in html
    assert "handshake HTTP 502" in html
    assert st.debug_view is True
