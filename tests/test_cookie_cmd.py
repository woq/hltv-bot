from hltv_bot.bot import DEFAULT_ADMIN_ID, HltvTelegramBot
from hltv_bot.session import BrowserSession, parse_cookie_line


class FakeTg:
    def __init__(self):
        self.sent = []
        self.deleted = []

    def send_rich(self, chat_id, html, **kwargs):
        self.sent.append(html)
        return {"message_id": 1}

    def send_message(self, chat_id, text):
        return self.send_rich(chat_id, text)

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)


def test_parse_cookie_line_strips_prefix():
    assert parse_cookie_line("Cookie: cf_clearance=abc; __cf_bm=x") == (
        "cf_clearance=abc; __cf_bm=x"
    )


def test_cookie_command_waits_then_saves(tmp_path):
    sess_path = tmp_path / "session.json"
    sess_path.write_text(
        '{"impersonate":"chrome131","user_agent":"UA","cookie":""}\n',
        encoding="utf-8",
    )
    sess = BrowserSession(impersonate="chrome131", headers={}, cookie="", path=sess_path)
    tg = FakeTg()
    bot = HltvTelegramBot(tg, sess)
    bot.handle_text(1, "/cookie", user_id=DEFAULT_ADMIN_ID)
    assert 1 in bot._await_cookie
    bot.handle_text(
        1,
        "Cookie: cf_clearance=tok; __cf_bm=bm",
        message_id=99,
        user_id=DEFAULT_ADMIN_ID,
    )
    assert 1 not in bot._await_cookie
    assert bot.session.has_clearance()
    assert 99 in tg.deleted
    assert any("已更新" in t for t in tg.sent)
