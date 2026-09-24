from datetime import datetime, timedelta, timezone

from hltv_bot.bot import DEFAULT_ADMIN_ID, HltvTelegramBot
from hltv_bot.reminders import CST, RemindConfig, _event_html, empty_state, plan_reminders, score_text
from hltv_bot.session import BrowserSession


def _match(**kw):
    base = {
        "id": "1",
        "team1": "G2",
        "team2": "Spirit",
        "event": "BLAST Open",
        "url": "https://www.hltv.org/matches/1/x",
        "live": "0",
        "stars": "3",
        "score1": "",
        "score2": "",
        "unix": "",
        "time": "21:00",
    }
    base.update(kw)
    return base


def _ev(**kw):
    base = {
        "id": "9",
        "name": "IEM Cologne 2026",
        "url": "https://www.hltv.org/events/9/iem",
        "live": False,
        "start_ts": 0,
        "location": "Cologne",
    }
    base.update(kw)
    return base


def test_score_text_ignores_empty():
    assert score_text({"score1": "", "score2": ""}) == ""
    assert score_text({"score1": "1", "score2": "0"}) == "1-0"


def test_first_poll_seeds_without_notices():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=CST)
    start = int((now + timedelta(minutes=10)).timestamp() * 1000)
    state, notes = plan_reminders(
        empty_state(),
        [_match(unix=str(start), live="1", score1="0", score2="0")],
        [_ev(start_ts=int((now + timedelta(days=3)).timestamp()))],
        now=now,
    )
    assert notes == []
    assert state["matches_seeded"] is True
    assert state["events_seeded"] is True
    assert state["matches"]["1"]["opened"] is False
    assert state["events"]["9"] == "days"


def test_match_soon_live_score_and_final():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    soon = int((now + timedelta(minutes=10)).timestamp() * 1000)
    cfg = RemindConfig(min_stars=1)
    state, notes = plan_reminders(empty_state(), [_match(unix=str(soon))], None, now=now, cfg=cfg)
    assert notes == []
    state, notes = plan_reminders(state, [], None, now=now, cfg=cfg)
    assert notes == []
    state, notes = plan_reminders(state, [_match(unix=str(soon))], None, now=now, cfg=cfg)
    assert [n.key for n in notes] == ["m:1:soon"]
    assert "即将开赛" in notes[0].html
    assert "UTC+8" in notes[0].html

    state, notes = plan_reminders(
        state,
        [_match(unix=str(soon), live="1", score1="0", score2="0")],
        None,
        now=now,
        cfg=cfg,
    )
    assert notes == []
    state, notes = plan_reminders(
        state,
        [_match(unix=str(soon), live="1", started="1", score1="0", score2="0")],
        None,
        now=now,
        cfg=cfg,
    )
    assert [n.key for n in notes] == ["m:1:live"]
    assert "已开赛" in notes[0].html

    state, notes = plan_reminders(
        state,
        [_match(unix=str(soon), live="1", score1="1", score2="0")],
        None,
        now=now,
        cfg=cfg,
    )
    assert notes[0].key == "m:1:score:1-0"
    assert "比分" in notes[0].html

    state, notes = plan_reminders(state, [], None, now=now, cfg=cfg)
    assert notes[0].key == "m:1:final"
    assert "结束" in notes[0].html
    assert "<code>1</code>" in notes[0].html and "<code>0</code>" in notes[0].html
    assert "1" not in state["matches"]


def test_low_star_or_non_tier_match_is_ignored():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    state, _ = plan_reminders(empty_state(), [_match(stars="0", live="1")], None, now=now)
    state, notes = plan_reminders(state, [_match(stars="0", live="1", score1="1", score2="0")], None, now=now)
    assert notes == []
    state, notes = plan_reminders(
        empty_state(),
        [_match(id="2", stars="3", event="CCT Season", live="1")],
        None,
        now=now,
    )
    state, notes = plan_reminders(
        state,
        [_match(id="2", stars="3", event="CCT Season", live="1", score1="1", score2="0")],
        None,
        now=now,
    )
    assert notes == []


def test_streak_mark_and_ignore_and_pause():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    cfg = RemindConfig()
    row = _match(live="1", started="1", score1="0", score2="0")
    state, notes = plan_reminders(empty_state(), [row], None, now=now, cfg=cfg)
    assert notes == []
    marked = None
    for n in range(1, 6):
        state, notes = plan_reminders(
            state,
            [_match(live="1", started="1", score1=str(n), score2="0")],
            None,
            now=now,
            cfg=cfg,
        )
        assert notes
        marked = notes[0].html
    assert marked is not None
    assert "连赢" in marked and "5" in marked
    assert "G2" in marked

    paused = RemindConfig(watch=False)
    state, notes = plan_reminders(state, [_match(live="1", started="1", score1="6", score2="0")], None, now=now, cfg=paused)
    assert notes == []

    ignored = RemindConfig(ignored=frozenset({"1"}))
    state, notes = plan_reminders(state, [_match(live="1", started="1", score1="7", score2="0")], None, now=now, cfg=ignored)
    assert notes == []


def test_event_stages_major_and_t1_only():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=CST)
    cfg = RemindConfig(event_days=7, event_hours=6)
    far = _ev(id="far", name="PGL Major Copenhagen", start_ts=int((now + timedelta(days=20)).timestamp()))
    days = _ev(id="days", name="BLAST Premier", start_ts=int((now + timedelta(days=3)).timestamp()))
    day = _ev(id="day", name="IEM Katowice", start_ts=int((now + timedelta(hours=20)).timestamp()))
    hours = _ev(id="hours", name="ESL Pro League", start_ts=int((now + timedelta(hours=5)).timestamp()))
    t2 = _ev(id="t2", name="CCT Season", start_ts=int((now + timedelta(days=2)).timestamp()))
    state, notes = plan_reminders(empty_state(), None, [far, days, day, hours, t2], now=now, cfg=cfg)
    assert notes == []
    assert "far" not in state["events"]
    assert "t2" not in state["events"]
    assert state["events"]["days"] == "days"
    assert state["events"]["day"] == "day"
    assert state["events"]["hours"] == "hours"

    later = now + timedelta(days=2, hours=12)
    state, notes = plan_reminders(state, None, [days], now=later, cfg=cfg)
    assert [n.key for n in notes] == ["e:days:day"]
    assert "还有" in notes[0].html
    flagged = _event_html(
        {**days, "country_code": "DE", "location": "Cologne"},
        now,
        "days",
    )
    assert "🇩🇪" in flagged
    assert "Cologne" in flagged

    closing = now + timedelta(days=2, hours=20)
    state, notes = plan_reminders(state, None, [days], now=closing, cfg=cfg)
    assert notes[0].key == "e:days:hours"
    assert "最后提醒" in notes[0].html
    state, notes = plan_reminders(state, None, [days], now=closing, cfg=cfg)
    assert notes == []


class _Tg:
    def send_message(self, chat_id, text, silent=False):
        self.last = text
        return {"message_id": 1}

    def delete_message(self, chat_id, message_id):
        return None


def test_ignore_stop_and_watch_commands(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    bot = HltvTelegramBot(
        _Tg(),
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={DEFAULT_ADMIN_ID},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot.handle_text(1, "/ignore 2396932", user_id=DEFAULT_ADMIN_ID)
    assert "2396932" in bot._cfg().ignored
    bot.handle_text(1, "/stop", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().watch is False
    bot.handle_text(1, "/watch", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().watch is True
    assert bot._state.get("quiet_all") is True
    bot.handle_text(1, "/unignore 2396932", user_id=DEFAULT_ADMIN_ID)
    assert "2396932" not in bot._cfg().ignored
    assert "2396932" in bot._state.get("quiet_ids")
