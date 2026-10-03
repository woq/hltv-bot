import time

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


def test_cmd_watch_summary_and_off(tmp_path, monkeypatch):
    tg = Tg()
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    bot = HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={1},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot._list_rows = [
        {
            "id": "101",
            "team1": "Spirit",
            "team2": "FaZe",
            "event": "BLAST Premier World Final",
            "stars": 4,
            "live": "1",
            "score1": "1",
            "score2": "0",
            "time": "LIVE",
        },
        {
            "id": "102",
            "team1": "MOUZ",
            "team2": "Vitality",
            "event": "BLAST Premier World Final",
            "stars": 3,
            "live": "0",
            "time": "20:30",
            "unix": int(time.time()) + 3600,
        },
    ]
    # Test turning on
    bot.handle_text(-100, "/watch", user_id=1)
    assert tg.sent
    text = tg.sent[-1][1]
    assert "已开启实时比分监控" in text
    assert ("今日" in text or "次日" in text) and "10:00" in text
    assert "Spirit" in text and "FaZe" in text
    assert "MOUZ" in text and "Vitality" in text
    assert "低功耗模式" in text

    # Test turning off
    tg.sent.clear()
    bot._cool._last.clear()
    bot.handle_text(-100, "/watch off", user_id=1)
    assert tg.sent
    assert tg.sent[-1][1] == "已关闭"


def test_concurrent_multi_matches_cards_independent(tmp_path, monkeypatch):
    from hltv_bot.reminders import Notice

    tg = Tg()
    seq = {"n": 100}

    def send_photo(chat_id, photo, caption="", filename="hltv.png", silent=False):
        seq["n"] += 1
        tg.sent.append((chat_id, caption, silent))
        return {"message_id": seq["n"]}

    tg.send_photo = send_photo
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    bot = HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={1},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    # Enable /watch for group -100
    bot.handle_text(-100, "/watch", user_id=1)
    tg.sent.clear()
    tg.edited.clear()

    # Match A (id=201) goes live
    note_a1 = Notice("m:201:preview", "<b>Match A 0-0</b>", {"view": "match"}, "201", "multi")
    bot._broadcast(note_a1)
    assert len(tg.sent) == 1
    assert tg.sent[-1][1] == "<b>Match A 0-0</b>"
    # Assigned message_id 101

    # Match B (id=202) also goes live simultaneously
    note_b1 = Notice("m:202:preview", "<b>Match B 0-0</b>", {"view": "match"}, "202", "multi")
    bot._broadcast(note_b1)
    assert len(tg.sent) == 2
    assert tg.sent[-1][1] == "<b>Match B 0-0</b>"
    # Assigned message_id 102

    # Match A score updates: should EDIT message 101, not 102
    note_a2 = Notice("m:201:score:1-0", "<b>Match A 1-0</b>", {"view": "match"}, "201", "multi")
    bot._broadcast(note_a2)
    assert len(tg.sent) == 2  # No new message sent
    assert len(tg.edited) == 1
    assert tg.edited[-1] == (-100, 101, "<b>Match A 1-0</b>")

    # Match B score updates: should EDIT message 102, not 101
    note_b2 = Notice("m:202:score:0-1", "<b>Match B 0-1</b>", {"view": "match"}, "202", "multi")
    bot._broadcast(note_b2)
    assert len(tg.sent) == 2  # Still 2 messages
    assert len(tg.edited) == 2
    assert tg.edited[-1] == (-100, 102, "<b>Match B 0-1</b>")

    # State verification: both matches are tracked with separate message IDs
    with bot._state_lock:
        msgs = bot._state.get("score_msgs", {})
        assert msgs["201"]["-100"] == 101
        assert msgs["202"]["-100"] == 102


def test_cmd_bump_replaces_and_updates_slot(tmp_path, monkeypatch):
    from hltv_bot.reminders import Notice

    tg = Tg()
    seq = {"n": 500}

    def send_photo(chat_id, photo, caption="", filename="hltv.png", silent=False):
        seq["n"] += 1
        tg.sent.append((chat_id, caption, silent))
        return {"message_id": seq["n"]}

    tg.send_photo = send_photo
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: [-100])
    bot = HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={1},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot.can_delete_in_chat = lambda cid: True
    bot._list_rows = [
        {
            "id": "301",
            "team1": "NaVi",
            "team2": "FaZe",
            "event": "Major",
            "stars": 4,
            "live": "1",
            "score1": "11",
            "score2": "9",
            "time": "LIVE",
        }
    ]
    # 1. Enable watch and broadcast initial score card
    bot.handle_text(-100, "/watch", user_id=1)
    note = Notice("m:301:score:11-9", "<b>NaVi 11-9 FaZe</b>", {"view": "match"}, "301", "multi")
    bot._broadcast(note)
    with bot._state_lock:
        bot._state.setdefault("matches", {})["301"] = {"live": True, "match_sent": False}
        assert bot._state["score_msgs"]["301"]["-100"] == 501

    # 2. Chat moves on, user issues /bump
    tg.sent.clear()
    tg.deleted.clear()
    bot.handle_text(-100, "/bump", user_id=2)
    # Old message 501 was deleted
    assert 501 in tg.deleted
    # New message was sent at bottom (message_id = 502)
    assert len(tg.sent) == 1
    assert "NaVi" in tg.sent[0][1] and "FaZe" in tg.sent[0][1]
    with bot._state_lock:
        assert bot._state["score_msgs"]["301"]["-100"] == 502

    # 3. Next score update: should edit message 502!
    next_note = Notice("m:301:score:12-9", "<b>NaVi 12-9 FaZe</b>", {"view": "match"}, "301", "multi")
    bot._broadcast(next_note)
    assert tg.edited[-1] == (-100, 502, "<b>NaVi 12-9 FaZe</b>")


def test_halftime_and_map_winner_send_photo_and_manage_slots(tmp_path, monkeypatch):
    from hltv_bot.reminders import Notice

    tg = Tg()
    seq = {"n": 600}

    def send_photo(chat_id, photo, caption="", filename="hltv.png", silent=False):
        seq["n"] += 1
        tg.sent.append((chat_id, caption, silent))
        return {"message_id": seq["n"]}

    tg.send_photo = send_photo
    timers = []

    def fake_timer(delay, fn, *args, **kwargs):
        timers.append((delay, fn))
        return type("T", (), {"start": lambda self: None})()

    monkeypatch.setattr("hltv_bot.bot.threading.Timer", fake_timer)
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: [-100])
    bot = HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={1},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot.handle_text(-100, "/watch", user_id=1)
    tg.sent.clear()
    tg.edited.clear()

    # 1. Initial live score -> sends photo (601)
    note_init = Notice("m:101:score:1-0|bo3", "<b>比分 1-0</b>", {"view": "match", "kind": "score"}, "101", "multi")
    bot._broadcast(note_init)
    assert len(tg.sent) == 1
    assert bot._state["score_msgs"]["101"]["-100"] == 601

    # 2. Score update (6-5) -> edits photo (601)
    note_edit = Notice("m:101:score:6-5|bo3", "<b>比分 6-5</b>", {"view": "match", "kind": "score"}, "101", "multi")
    bot._broadcast(note_edit)
    assert len(tg.sent) == 1  # No new message sent
    assert tg.edited[-1] == (-100, 601, "<b>比分 6-5</b>")

    # 3. Halftime (7-5) -> bumps live card (deletes 601, sends 602), then sends halftime photo (603)!
    # Halftime photo (603) should be auto-deleted with medium TTL (300s).
    timers.clear()
    note_ht = Notice("m:101:halftime:0", "<b>半场 7-5</b>", {"view": "match", "kind": "halftime"}, "101", "multi")
    bot._broadcast(note_ht)
    assert 601 in tg.deleted
    assert len(tg.sent) == 3
    # slot holds the bumped live card (602), NOT the halftime photo (603)
    assert bot._state["score_msgs"]["101"]["-100"] == 602
    assert any(delay == 300.0 for delay, _ in timers)

    # 4. Next round (8-5) -> edits the bumped live card (602), leaving halftime photo intact!
    note_edit2 = Notice("m:101:score:8-5|bo3", "<b>比分 8-5</b>", {"view": "match", "kind": "score"}, "101", "multi")
    bot._broadcast(note_edit2)
    assert len(tg.sent) == 3
    assert tg.edited[-1] == (-100, 602, "<b>比分 8-5</b>")

    # 5. Map winner -> deletes old live card (602), sends NEW photo (604), slot cleared!
    # Map winner photo (604) should be auto-deleted with long TTL (900s).
    timers.clear()
    note_map = Notice("m:101:map:0", "<b>Map winner 13-10</b>", {"view": "match", "kind": "map"}, "101", "multi")
    bot._broadcast(note_map)
    assert 602 in tg.deleted
    assert len(tg.sent) == 4
    assert "-100" not in bot._state.get("score_msgs", {}).get("101", {})
    assert any(delay == 900.0 for delay, _ in timers)

    # 6. Map 2 round 1 (1-0) -> sends NEW photo (605) for Map 2!
    note_m2 = Notice("m:101:score:1-0_m2", "<b>比分 1-0</b>", {"view": "match", "kind": "score"}, "101", "multi")
    bot._broadcast(note_m2)
    assert len(tg.sent) == 5
    assert bot._state["score_msgs"]["101"]["-100"] == 605


def test_deletes_own_score_message_even_when_not_admin_in_group(tmp_path, monkeypatch):
    """A bot can always delete its own messages in Telegram even if bot_can_delete_messages is False."""
    from hltv_bot.reminders import Notice

    tg = Tg()
    tg.bot_can_delete_messages = lambda chat_id: False  # Bot is NOT an admin in group!
    seq = {"n": 700}

    def send_photo(chat_id, photo, caption="", filename="hltv.png", silent=False):
        seq["n"] += 1
        tg.sent.append((chat_id, caption, silent))
        return {"message_id": seq["n"]}

    tg.send_photo = send_photo
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    monkeypatch.setattr("hltv_bot.bot.group_ids", lambda: [-100])
    bot = HltvTelegramBot(
        tg,
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={1},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot.handle_text(-100, "/watch", user_id=1)
    tg.sent.clear()
    tg.edited.clear()
    tg.deleted.clear()

    # 1. Live score sends photo (701)
    note_init = Notice("m:201:score:1-0|bo3", "<b>比分 1-0</b>", {"view": "match", "kind": "score"}, "201", "multi")
    bot._broadcast(note_init)
    assert bot._state["score_msgs"]["201"]["-100"] == 701

    # 2. Halftime bumps and MUST delete 701 even without admin permissions
    note_ht = Notice("m:201:halftime:0", "<b>半场 7-5</b>", {"view": "match", "kind": "halftime"}, "201", "multi")
    bot._broadcast(note_ht)
    assert 701 in tg.deleted
    assert bot._state["score_msgs"]["201"]["-100"] == 702

    # 3. Map winner MUST delete bumped live card (702) even without admin permissions
    note_map = Notice("m:201:map:0", "<b>Map winner 13-10</b>", {"view": "match", "kind": "map"}, "201", "multi")
    bot._broadcast(note_map)
    assert 702 in tg.deleted
    assert "-100" not in bot._state.get("score_msgs", {}).get("201", {})





