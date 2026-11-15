"""Owner vs group-mod command gates."""

from hltv_bot.bot import DEFAULT_ADMIN_ID, HltvTelegramBot
from hltv_bot.session import BrowserSession


class Tg:
    def __init__(self):
        self.sent: list[str] = []
        self._status = "member"

    def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        return {"message_id": 1}

    def send_photo(self, *a, **k):
        return {"message_id": 1}

    def delete_message(self, *a, **k):
        return None

    def chat_member_status(self, chat_id, user_id):
        return self._status

    def chat_admin_user_ids(self, chat_id):
        return set()


def _bot(tmp_path, tg=None):
    tg = tg or Tg()
    return tg, HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={DEFAULT_ADMIN_ID},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )


def test_group_admin_can_watch_not_cookie(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: {-100})
    tg, bot = _bot(tmp_path)
    tg._status = "administrator"
    bot.handle_text(-100, "/watch", user_id=42, chat_type="supergroup")
    assert str(-100) in (bot._saved().get("score_multi") or [])
    tg.sent.clear()
    bot.handle_text(-100, "/cookie", user_id=42, chat_type="supergroup")
    assert any("仅 owner" in t for t in tg.sent)


def test_member_cannot_watch(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: {-100})
    tg, bot = _bot(tmp_path)
    tg._status = "member"
    bot.handle_text(-100, "/watch", user_id=42, chat_type="supergroup")
    assert str(-100) not in (bot._saved().get("score_multi") or [])
    assert any("本群管理员" in t for t in tg.sent)


def test_group_admin_cannot_remote_allow(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: set())
    monkeypatch.setattr("hltv_bot.bot.add_group", lambda *a, **k: True)
    tg, bot = _bot(tmp_path)
    tg._status = "administrator"
    bot.handle_text(-100, "/allow -100999", user_id=42, chat_type="supergroup")
    assert any("远程授权" in t for t in tg.sent)


def test_stop_only_clears_this_chat(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: {-100, -200})
    tg, bot = _bot(tmp_path)
    bot._write_settings({"score_multi": ["-100", "-200"], "score_single": ["-100"], "event_watch": True})
    bot.handle_text(-100, "/stop", user_id=DEFAULT_ADMIN_ID, chat_type="supergroup")
    saved = bot._saved()
    assert saved.get("score_multi") == ["-200"]
    assert saved.get("score_single") == []
    assert saved.get("event_watch") is True
