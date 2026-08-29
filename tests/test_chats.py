import os

from hltv_bot.bot import DEFAULT_ADMIN_ID, HltvTelegramBot
from hltv_bot.chats import add_group, group_ids, list_groups, remove_group
from hltv_bot.session import BrowserSession


def test_add_list_remove_group(tmp_path):
    p = tmp_path / "chats.json"
    assert add_group(-1001, "priv", path=p) is True
    assert add_group(-1001, "priv", path=p) is False
    assert group_ids(p) == {-1001}
    assert list_groups(p)[0]["title"] == "priv"
    assert remove_group(-1001, path=p) is True
    assert group_ids(p) == set()


class _Tg:
    def send_rich(self, chat_id, html, **kwargs):
        return {"message_id": 1}

    def send_message(self, chat_id, text):
        return self.send_rich(chat_id, text)

    def chat_member_status(self, chat_id, user_id):
        return ""

    def chat_admin_user_ids(self, chat_id):
        return set()


def test_non_admin_cannot_allow(tmp_path):
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        (tmp_path / "data").mkdir()
        sess = BrowserSession("chrome131", {}, "", path=tmp_path / "s.json")
        bot = HltvTelegramBot(_Tg(), sess, admin_ids={DEFAULT_ADMIN_ID})
        bot.handle_text(-100, "/allow", user_id=1, chat_title="g", chat_type="supergroup")
        assert group_ids() == set()
    finally:
        os.chdir(old)


def test_admin_allow_current_group(tmp_path):
    old = os.getcwd()
    os.chdir(tmp_path)
    try:
        (tmp_path / "data").mkdir()
        sess = BrowserSession("chrome131", {}, "", path=tmp_path / "s.json")
        bot = HltvTelegramBot(_Tg(), sess, admin_ids={DEFAULT_ADMIN_ID})
        bot.handle_text(
            -10099,
            "/allow",
            user_id=DEFAULT_ADMIN_ID,
            chat_title="CS",
            chat_type="supergroup",
        )
        assert -10099 in group_ids()
    finally:
        os.chdir(old)
