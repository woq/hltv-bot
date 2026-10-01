from datetime import datetime, timedelta, timezone

from hltv_bot.bot import BOT_COMMANDS, DEFAULT_ADMIN_ID, HltvTelegramBot, command_jobs, command_scope_clears
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
    assert state["matches"]["1"]["score"] == "0-0"
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
    assert notes == []

    state, notes = plan_reminders(
        state,
        [_match(unix=str(soon), live="1", score1="0", score2="0", format="bo3")],
        None,
        now=now,
        cfg=cfg,
    )
    assert [n.key for n in notes] == ["m:1:preview"]
    assert "预告" in notes[0].html
    assert "0" in notes[0].html
    assert notes[0].card["note"] == ""
    assert "当前图" not in notes[0].html
    assert "系列" not in notes[0].html
    state, notes = plan_reminders(
        state,
        [_match(unix=str(soon), live="1", score1="0", score2="0", format="bo3")],
        None,
        now=now,
        cfg=cfg,
    )
    assert notes == []
    state, notes = plan_reminders(
        state,
        [_match(unix=str(soon), live="1", score1="1", score2="0", format="bo3")],
        None,
        now=now,
        cfg=cfg,
    )
    assert notes[0].key == "m:1:score:1-0|bo3"
    assert "比分" in notes[0].html
    assert "当前图" not in notes[0].html
    assert "系列" not in notes[0].html
    assert "已开赛" not in notes[0].html

    state, notes = plan_reminders(state, [], None, now=now, cfg=cfg)
    assert notes[0].key == "m:1:match"
    assert notes[0].card["label"] == "Match winner"
    assert "<code>1</code>" in notes[0].html and "<code>0</code>" in notes[0].html
    assert "1" not in state["matches"]


def test_same_map_score_only_moves_forward():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    row = _match(
        live="1",
        score1="12",
        score2="9",
        format="bo3",
        maps="Ancient · Nuke · Inferno",
        map_index="0",
        won1="0",
        won2="0",
    )
    state, notes = plan_reminders(empty_state(), [row], None, now=now)
    assert notes == []
    state, notes = plan_reminders(state, [{**row, "score1": "11", "score2": "7"}], None, now=now)
    assert notes == []
    assert state["matches"]["1"]["score"] == "12-9"
    state, notes = plan_reminders(state, [{**row, "score1": "12", "score2": "10"}], None, now=now)
    assert [item["name"] for item in notes[0].card["map_rows"]] == ["Ancient", "Nuke", "Inferno"]
    assert notes[0].card["map_rows"][0]["current"] is True
    assert "系列" not in notes[0].html
    done = {**row, "score1": "13", "score2": "11", "won1": "1", "won2": "0"}
    state, notes = plan_reminders(state, [done], None, now=now)
    assert notes[0].card["label"] == "Map winner"
    assert notes[0].card["winner"] == 1
    assert notes[0].card["pair"] == ("13", "11")
    assert notes[0].card["map_rows"][0]["winner"] == 1
    assert "系列" not in notes[0].html
    state, notes = plan_reminders(state, [done], None, now=now)
    assert notes == []
    fresh = {**done, "score1": "0", "score2": "0", "map_index": "1"}
    state, notes = plan_reminders(state, [fresh], None, now=now)
    assert notes == []
    assert state["matches"]["1"]["score"] == "0-0"
    state, notes = plan_reminders(state, [{**fresh, "score1": "1", "score2": "0"}], None, now=now)
    assert notes[0].card["label"] == "比分"
    assert notes[0].card["map_rows"][0]["winner"] == 1
    assert notes[0].card["map_rows"][1]["name"] == "Nuke"
    assert notes[0].card["map_rows"][1]["current"] is True
    assert "系列" not in notes[0].html
    end = {**fresh, "score1": "13", "score2": "5", "won1": "2", "won2": "0", "map_index": "1"}
    state, notes = plan_reminders(state, [end], None, now=now)
    assert notes[0].key == "m:1:match"
    assert notes[0].card["label"] == "Match winner"
    assert notes[0].card["pair"] == ("2", "0")
    assert notes[0].card["map_score"] == "本图 13–5"
    assert notes[0].card["map_rows"][1]["winner"] == 1
    assert "系列" not in notes[0].html
    state, notes = plan_reminders(state, [], None, now=now)
    assert notes == []


def test_series_and_map_rounds_never_shrink():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    done = _match(
        live="1",
        score1="13",
        score2="11",
        format="bo3",
        maps="Ancient · Nuke · Inferno",
        map_index="0",
        won1="1",
        won2="0",
    )
    state, _ = plan_reminders(empty_state(), [done], None, now=now)
    dipped = {**done, "score1": "4", "score2": "2", "won1": "0", "won2": "0", "map_index": "0"}
    state, notes = plan_reminders(state, [dipped], None, now=now)
    saved = state["matches"]["1"]
    assert saved["won1"] == "1" and saved["won2"] == "0"
    assert saved["score"] == "4-2"
    assert saved["map_index"] == "1"
    assert saved["map_rounds"] == "13-11,4-2"
    assert notes[0].card["label"] == "比分"
    state, notes = plan_reminders(
        state,
        [{**dipped, "score1": "3", "score2": "1", "won1": "1", "won2": "0"}],
        None,
        now=now,
    )
    assert notes == []
    assert state["matches"]["1"]["score"] == "4-2"
    assert state["matches"]["1"]["map_rounds"] == "13-11,4-2"
    state, notes = plan_reminders(
        state,
        [{**done, "score1": "4", "score2": "3", "won1": "", "won2": "", "map_index": "0"}],
        None,
        now=now,
    )
    assert state["matches"]["1"]["won1"] == "1"
    assert state["matches"]["1"]["score"] == "4-3"
    assert notes[0].card["map_rows"][0]["winner"] == 1
    assert notes[0].card["map_rows"][1]["current"] is True


def test_missing_series_tally_still_opens_the_next_map():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    finished = _match(
        live="1",
        score1="13",
        score2="5",
        format="bo3",
        maps="Ancient · Nuke",
        map_index="0",
        won1="",
        won2="",
    )
    state, _ = plan_reminders(empty_state(), [finished], None, now=now)
    state, notes = plan_reminders(
        state,
        [{**finished, "score1": "2", "score2": "0"}],
        None,
        now=now,
    )
    saved = state["matches"]["1"]
    assert saved["won1"] == "1" and saved["won2"] == "0"
    assert saved["score"] == "2-0"
    assert saved["map_index"] == "1"
    assert saved["map_rounds"] == "13-5,2-0"
    assert notes[0].card["label"] == "比分"
    assert notes[0].card["map_rows"][0]["winner"] == 1
    assert notes[0].card["map_rows"][1]["current"] is True


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


def test_bo1_score_note_and_pause():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    cfg = RemindConfig()
    state, notes = plan_reminders(empty_state(), [_match(live="1", score1="0", score2="0", format="bo1")], None, now=now, cfg=cfg)
    assert notes == []
    state, notes = plan_reminders(
        state,
        [_match(live="1", score1="13", score2="9", format="bo1")],
        None,
        now=now,
        cfg=cfg,
    )
    assert notes[0].card["label"] == "Match winner"
    assert notes[0].card["pair"] == ("13", "9")
    assert notes[0].key == "m:1:match"
    assert "当前图" not in notes[0].html
    assert "13" in notes[0].html

    paused = RemindConfig(watch=False)
    state, notes = plan_reminders(state, [_match(live="1", score1="13", score2="10", format="bo1")], None, now=now, cfg=paused)
    assert notes == []

    ignored = RemindConfig(ignored=frozenset({"1"}))
    state, notes = plan_reminders(state, [_match(live="1", score1="13", score2="11", format="bo1")], None, now=now, cfg=ignored)
    assert notes == []


def test_event_bells_at_nine_and_six():
    cfg = RemindConfig(event_days=7, event_hours=6)
    start = datetime(2026, 10, 3, 18, 0, tzinfo=CST)
    ev = _ev(id="8244", name="ESL Pro League Season 24", start_ts=int(start.timestamp()))
    far = _ev(id="far", name="PGL Major Copenhagen", start_ts=int((start + timedelta(days=20)).timestamp()))
    t2 = _ev(id="t2", name="CCT Season", start_ts=int(start.timestamp()))
    morning = datetime(2026, 10, 2, 9, 0, tzinfo=CST)
    state, notes = plan_reminders(empty_state(), None, [far, ev, t2], now=morning, cfg=cfg)
    assert notes == []
    assert state["events"]["8244"] == "day"
    assert "far" not in state["events"]
    assert "t2" not in state["events"]
    assert "09" not in (state.get("event_bells") or {}).get("2026-10-02", [])

    state, notes = plan_reminders(state, None, [far, ev, t2], now=morning, cfg=cfg)
    assert [n.key for n in notes] == ["e:8244:2026-10-01:18", "e:8244:2026-10-02:09"]
    assert notes[-1].card["view"] == "event"
    assert "1 天" in notes[-1].html
    flagged = _event_html({**ev, "country_code": "DE", "location": "Cologne"}, morning, "day")
    assert "🇩🇪" in flagged
    assert "Cologne" in flagged

    state, notes = plan_reminders(state, None, [ev], now=morning.replace(hour=12), cfg=cfg)
    assert notes == []

    evening = datetime(2026, 10, 2, 18, 0, tzinfo=CST)
    state, notes = plan_reminders(state, None, [ev], now=evening, cfg=cfg)
    assert [n.key for n in notes] == ["e:8244:2026-10-02:18"]
    assert "24 小时" in notes[0].html

    early = _ev(id="early", name="IEM Katowice", start_ts=int(datetime(2026, 10, 4, 12, 0, tzinfo=CST).timestamp()))
    at = datetime(2026, 10, 4, 9, 0, tzinfo=CST)
    state, notes = plan_reminders(state, None, [early], now=at, cfg=cfg)
    assert [n.key for n in notes] == ["e:early:2026-10-03:18", "e:early:2026-10-04:09"]
    assert "最后提醒" in notes[-1].html
    assert state["events"]["early"] == "hours"


def test_missed_event_bell_is_sent_later():
    cfg = RemindConfig(event_days=7, event_hours=6)
    start = datetime(2026, 10, 3, 18, 0, tzinfo=CST)
    ev = _ev(id="8244", name="ESL Pro League Season 24", start_ts=int(start.timestamp()))
    morning = datetime(2026, 10, 2, 9, 0, tzinfo=CST)
    state, notes = plan_reminders(empty_state(), None, [ev], now=morning, cfg=cfg)
    assert notes == []
    late = datetime(2026, 10, 2, 11, 20, tzinfo=CST)
    state, notes = plan_reminders(state, None, [ev], now=late, cfg=cfg)
    assert [n.key for n in notes] == ["e:8244:2026-10-01:18", "e:8244:2026-10-02:09"]
    early = datetime(2026, 10, 3, 8, 10, tzinfo=CST)
    state, notes = plan_reminders(state, None, [ev], now=early, cfg=cfg)
    assert [n.key for n in notes] == ["e:8244:2026-10-02:18"]


def test_poll_is_fast_only_while_live():
    from hltv_bot.reminders import LIVE_POLL, QUIET_POLL, SOON_POLL, choose_poll_wait

    now = datetime(2026, 9, 24, 12, 0, tzinfo=CST)
    later = int((now + timedelta(hours=5)).timestamp() * 1000)
    soon = int((now + timedelta(minutes=20)).timestamp() * 1000)
    far = int((now + timedelta(days=3)).timestamp() * 1000)
    sent = {"2026-09-24": ["10"]}
    bells = {"2026-09-23": ["09", "18"], "2026-09-24": ["09", "18"]}
    assert choose_poll_wait([_match(unix=str(far))], RemindConfig(), now, sent, None, bells) == 3600
    assert choose_poll_wait([_match(unix=str(later))], RemindConfig(), now, sent, None, bells) == 3600
    assert choose_poll_wait([_match(unix=str(far))], RemindConfig(), now, {}, None, bells) == SOON_POLL
    assert choose_poll_wait([_match(unix=str(soon))], RemindConfig(), now, {}, None, bells) == SOON_POLL
    assert choose_poll_wait([_match(live="1", score1="1", score2="0")], RemindConfig(), now, {}, None, bells) == LIVE_POLL
    assert choose_poll_wait([_match(unix=str(far))], RemindConfig(watch=False, event_watch=False), now, {}) == QUIET_POLL
    # 20 minutes before the bell used to fall through to the 6-hour nap.
    far_unix = str(far)
    before_evening = datetime(2026, 9, 24, 19, 40, tzinfo=CST)
    assert choose_poll_wait([_match(unix=far_unix)], RemindConfig(), before_evening, sent, None, bells) == 20 * 60
    before_morning = datetime(2026, 9, 24, 9, 40, tzinfo=CST)
    assert choose_poll_wait([_match(unix=far_unix)], RemindConfig(), before_morning, {"2026-09-23": ["20"]}, None, bells) == 20 * 60
    before_event = datetime(2026, 9, 24, 8, 40, tzinfo=CST)
    assert choose_poll_wait(
        [_match(unix=far_unix)],
        RemindConfig(),
        before_event,
        {"2026-09-23": ["20"]},
        None,
        bells,
    ) == 20 * 60
    late_morning = datetime(2026, 9, 24, 9, 5, tzinfo=CST)
    assert choose_poll_wait([_match(unix=far_unix)], RemindConfig(), late_morning, sent) == SOON_POLL
    # Next event stage is the 48-hour mark, one hour from a start 49 hours out.
    soon_ev = _ev(start_ts=int((now + timedelta(hours=49)).timestamp()))
    assert choose_poll_wait([_match(unix=far_unix)], RemindConfig(), now, sent, [soon_ev], bells) == 3600


def test_digest_crosses_midnight_and_splits_evening():
    morning = datetime(2026, 9, 24, 9, 0, tzinfo=CST)
    night = int(datetime(2026, 9, 25, 2, 0, tzinfo=CST).timestamp() * 1000)
    afternoon = int(datetime(2026, 9, 24, 15, 0, tzinfo=CST).timestamp() * 1000)
    rows = [
        _match(id="night", unix=str(night), event_id="77"),
        _match(id="day", unix=str(afternoon), event_id="77"),
    ]
    state, notes = plan_reminders(empty_state(), rows, None, now=morning)
    assert notes == []
    at_ten = datetime(2026, 9, 24, 10, 5, tzinfo=CST)
    state, notes = plan_reminders(state, rows, None, now=at_ten)
    assert [n.key for n in notes] == ["d:2026-09-24:10"]
    assert "02:00" in notes[0].html and "15:00" in notes[0].html
    assert notes[0].card["title"].startswith("赛程")
    state, notes = plan_reminders(state, rows, None, now=at_ten)
    assert notes == []
    at_eight = datetime(2026, 9, 24, 20, 5, tzinfo=CST)
    state, notes = plan_reminders(state, rows, None, now=at_eight)
    assert [n.key for n in notes] == ["d:2026-09-24:20"]
    assert "02:00" in notes[0].html
    assert "15:00" not in notes[0].html
    state, notes = plan_reminders(state, rows, None, now=at_eight, cfg=RemindConfig(event_watch=False))
    assert notes == []


def test_restart_inside_digest_window_still_sends():
    at_ten = datetime(2026, 9, 24, 10, 5, tzinfo=CST)
    afternoon = int(datetime(2026, 9, 24, 15, 0, tzinfo=CST).timestamp() * 1000)
    rows = [_match(id="day", unix=str(afternoon), event_id="77")]
    state, notes = plan_reminders(empty_state(), rows, None, now=at_ten)
    assert notes == []
    assert "10" not in {str(x) for x in (state.get("digests") or {}).get("2026-09-24", [])}
    state, notes = plan_reminders(state, rows, None, now=at_ten)
    assert [n.key for n in notes] == ["d:2026-09-24:10"]


def test_follow_and_cover_bypass_tier_ignore_still_wins():
    now = datetime(2026, 9, 24, 18, 0, tzinfo=CST)
    low = _match(id="9", stars="0", event="CCT Season", event_id="55", live="1", score1="0", score2="0")
    state, notes = plan_reminders(empty_state(), [low], None, now=now, cfg=RemindConfig(followed=frozenset({"9"})))
    assert "9" in state["matches"]
    state, notes = plan_reminders(state, [{**low, "score1": "2", "score2": "1"}], None, now=now, cfg=RemindConfig(followed=frozenset({"9"})))
    assert notes and notes[0].key.startswith("m:9:score")
    covered = RemindConfig(covered=frozenset({"55"}))
    other = _match(id="8", stars="0", event="CCT Season", event_id="55", live="1", score1="1", score2="0")
    state, notes = plan_reminders(empty_state(), [other], None, now=now, cfg=covered)
    assert "8" in state["matches"]
    state, notes = plan_reminders(
        state,
        [{**other, "score1": "3"}],
        None,
        now=now,
        cfg=RemindConfig(covered=frozenset({"55"}), ignored=frozenset({"8"})),
    )
    assert notes == []


def test_event_watch_off_records_stage_without_notice():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=CST)
    days = _ev(id="days", name="BLAST Premier", start_ts=int((now + timedelta(days=3)).timestamp()))
    state, notes = plan_reminders(empty_state(), None, [days], now=now)
    assert notes == []
    later = now + timedelta(days=2, hours=12)
    state, notes = plan_reminders(state, None, [days], now=later, cfg=RemindConfig(event_watch=False))
    assert notes == []
    assert state["events"]["days"] == "day"
    state, notes = plan_reminders(state, None, [days], now=later)
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
    bot.handle_text(1, "/follow", user_id=DEFAULT_ADMIN_ID)
    bot._cool._last.clear()
    bot.handle_text(1, "/stop", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().watch is False
    assert bot._cfg().score_multi == frozenset()
    assert bot._cfg().score_single == frozenset()
    assert bot._cfg().event_watch is False
    bot.handle_text(1, "/watch", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().watch is True
    assert bot._cfg().score_multi == frozenset({"1"})
    assert bot._state.get("quiet_all") is True
    bot.handle_text(1, "/unignore 2396932", user_id=DEFAULT_ADMIN_ID)
    assert "2396932" not in bot._cfg().ignored
    assert "2396932" in bot._state.get("quiet_ids")
    bot.handle_text(1, "/untrack", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().event_watch is False
    assert bot._cfg().watch is True
    bot.handle_text(1, "/track", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().event_watch is True
    bot.handle_text(2, "/follow", user_id=DEFAULT_ADMIN_ID)
    assert "2" in bot._cfg().score_single
    bot._cool._last.clear()
    bot.handle_text(2, "/follow off", user_id=DEFAULT_ADMIN_ID)
    assert "2" not in bot._cfg().score_single
    bot._cool._last.clear()
    bot.handle_text(1, "/follow 42", user_id=DEFAULT_ADMIN_ID)
    bot.handle_text(1, "/cover 77", user_id=DEFAULT_ADMIN_ID)
    bot.handle_text(1, "/digest 10 20", user_id=DEFAULT_ADMIN_ID)
    bot.handle_text(1, "/window 7 6", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().followed == frozenset({"42"})
    assert bot._cfg().score_single == frozenset({"1"})
    assert bot._cfg().covered == frozenset({"77"})
    assert (bot._cfg().digest_morning, bot._cfg().digest_evening) == (10, 20)
    assert (bot._cfg().event_days, bot._cfg().event_hours) == (7, 6)
    bot.handle_text(1, "/unfollow 42", user_id=DEFAULT_ADMIN_ID)
    bot.handle_text(1, "/uncover 77", user_id=DEFAULT_ADMIN_ID)
    assert bot._cfg().followed == frozenset()
    assert bot._cfg().covered == frozenset()


def test_reminder_command_sends_this_chat_only(tmp_path, monkeypatch):
    monkeypatch.setattr("hltv_bot.bot.threading.Timer", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    sent: list[tuple] = []

    class Tg(_Tg):
        def send_photo(self, chat_id, photo, caption="", filename="hltv.png", silent=False):
            sent.append((chat_id, caption, photo))
            return {"message_id": 9}

    start = datetime(2026, 10, 3, 18, 0, tzinfo=CST)
    ev = _ev(id="8244", name="ESL Pro League Season 24", start_ts=int(start.timestamp()))
    monkeypatch.setattr("hltv_bot.bot.fetch_events", lambda session: [ev])
    monkeypatch.setattr("hltv_bot.cards.render_card", lambda card: b"png")
    bot = HltvTelegramBot(
        Tg(),
        BrowserSession("chrome131", {}, "cf_clearance=x"),
        admin_ids={DEFAULT_ADMIN_ID},
        state_path=tmp_path / "state.json",
        settings_path=tmp_path / "settings.json",
    )
    bot.handle_text(DEFAULT_ADMIN_ID, "/reminder", user_id=DEFAULT_ADMIN_ID)
    assert len(sent) == 1
    assert sent[0][0] == DEFAULT_ADMIN_ID
    assert "ESL Pro League" in sent[0][1]
    assert bot._state.get("event_bells") in (None, {})


def test_command_menu_is_one_full_list():
    names = [row["command"] for row in BOT_COMMANDS]
    assert names[:3] == ["matches", "events", "hltv"]
    for cmd in ("watch", "stop", "track", "untrack", "follow", "cover", "digest", "reminder", "ignore", "allow", "cookie", "status"):
        assert cmd in names
    assert "debug" not in names
    jobs = command_jobs({DEFAULT_ADMIN_ID}, {-100})
    assert jobs == [(BOT_COMMANDS, None)]
    clears = command_scope_clears({7, DEFAULT_ADMIN_ID}, {-200, -100})
    assert clears[0] == {"type": "all_private_chats"}
    assert {"type": "all_group_chats"} in clears
    assert {"type": "chat", "chat_id": 7} in clears
    assert {"type": "chat_member", "chat_id": -200, "user_id": 7} in clears
