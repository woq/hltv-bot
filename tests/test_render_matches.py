from hltv_bot.fixtures import MOCK_MATCHES
from hltv_bot.render import classify_event_tier, tier_rank, render_matches_image, localize_team
from hltv_bot.bot import HltvTelegramBot, WatchState
from hltv_bot.session import BrowserSession


def test_classify_event_tier():
    # T1 cases
    assert classify_event_tier("PGL CS2 Major Copenhagen 2024", 0) == "T1"
    assert classify_event_tier("IEM Cologne 2026", 1) == "T1"
    assert classify_event_tier("BLAST Premier World Final", 2) == "T1"
    assert classify_event_tier("Random Local Cup", 4) == "T1"  # 4-5 stars

    # T2 cases
    assert classify_event_tier("CCT Season 2 Europe Series 1", 1) == "T2"
    assert classify_event_tier("ESL Challenger League Season 50", 1) == "T2"
    assert classify_event_tier("Thunderpick World Championship", 0) == "T2"
    assert classify_event_tier("Low Tier Event", 2) == "T2"  # 2-3 stars

    # T3 cases
    assert classify_event_tier("CCT 2026 Europe Series 8 Closed Qualifier", 0) == "T3"
    assert classify_event_tier("ESEA Main Season 51", 0) == "T3"
    assert classify_event_tier("Random Cup", 1) == "T3"

    # Other cases
    assert classify_event_tier("Unknown Lan Cup", 0) == "Other"


def test_tier_rank_ordering():
    assert tier_rank("T1") < tier_rank("T2")
    assert tier_rank("T2") < tier_rank("T3")
    assert tier_rank("T3") < tier_rank("Other")


def test_localize_team():
    assert localize_team("The MongolZ") == "The MongolZ"
    assert localize_team("Spirit") == "Spirit"
    assert localize_team("G2") == "G2"


def test_render_matches_image_bytes():
    img_bytes = render_matches_image(MOCK_MATCHES, tier_filter="T3")
    assert len(img_bytes) > 1000
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    # Test empty filter
    empty_bytes = render_matches_image([], tier_filter="T1")
    assert len(empty_bytes) > 500
    assert empty_bytes[:8] == b"\x89PNG\r\n\x1a\n"


class _MockTg:
    def __init__(self):
        self.sent = []
        self.photos = []
        self.deleted = []
        self.bot_permissions = {}

    def send_photo(self, chat_id, photo_bytes, caption="", filename="matches.png"):
        self.photos.append((chat_id, photo_bytes, caption))
        return {"message_id": 100 + len(self.photos)}

    def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"message_id": 200 + len(self.sent)}

    def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    def bot_can_delete_messages(self, chat_id, bot_user_id=None):
        return self.bot_permissions.get(int(chat_id), False)


def test_cmd_matches_sends_photo_and_shortcuts(monkeypatch):
    tg = _MockTg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "", path=None), admin_ids={1})
    monkeypatch.setattr("hltv_bot.bot.fetch_matches", lambda sess: list(MOCK_MATCHES))

    bot._cmd_matches(1, "")
    assert len(tg.photos) == 1
    chat_id, data, caption = tg.photos[0]
    assert chat_id == 1
    assert len(data) > 1000
    assert "HLTV Matches" in caption
    assert "/watch 2396932" in caption

    # Text mode
    bot._cmd_matches(1, "text")
    assert len(tg.sent) == 1
    assert "BLAST" in tg.sent[0][1]


def test_user_command_delete_permission():
    tg = _MockTg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "", path=None), admin_ids={1})

    # Group -100 without delete permission
    tg.bot_permissions[-100] = False
    bot.handle_text(-100, "/help", user_id=1, chat_type="supergroup", message_id=88)
    assert (-100, 88) not in bot.tg.deleted

    # Group -200 with delete permission
    tg.bot_permissions[-200] = True
    bot.msg_ttl = 0.01
    bot.handle_text(-200, "/help", user_id=1, chat_type="supergroup", message_id=99)
    import time
    time.sleep(0.05)
    assert (-200, 99) in bot.tg.deleted
