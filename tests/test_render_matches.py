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


def test_build_matches_html_unified_event_tier():
    from hltv_bot.render import build_matches_html
    # Matches from the same event with different stars (e.g., 5-star and 2-star)
    matches = [
        {
            "id": "1",
            "team1": "A",
            "team2": "B",
            "event": "BLAST Premier",
            "live": "0",
            "stars": "5",
            "time": "12:00",
        },
        {
            "id": "2",
            "team1": "C",
            "team2": "D",
            "event": "BLAST Premier",
            "live": "0",
            "stars": "2",
            "time": "15:00",
        },
    ]
    html = build_matches_html(matches, tier_filter="T2")
    # BLAST Premier should only appear once in event-name
    assert html.count("BLAST Premier") == 1
    # Both matches should be grouped under that single event banner
    assert "2 MATCHES" in html

    # Test both TBD are excluded
    matches_with_tbd = matches + [
        {"id": "3", "team1": "TBD", "team2": "TBD", "event": "BLAST Premier", "live": "0", "stars": "3", "time": "18:00"}
    ]
    html2 = build_matches_html(matches_with_tbd, tier_filter="T2")
    assert "2 MATCHES" in html2


def test_localize_team():
    assert localize_team("The MongolZ") == "The MongolZ"
    assert localize_team("Spirit") == "Spirit"
    assert localize_team("G2") == "G2"


def test_build_matches_html_empty_placeholder_and_page_logo():
    from hltv_bot.render import build_matches_html

    empty = build_matches_html([], tier_filter="T1")
    assert 'class="empty-card"' in empty
    assert "No matches" in empty
    assert "Nothing scheduled for T1 · try /matches t2" in empty

    png = (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00" * 80
    )
    # Minimal valid-enough cache file is sniffed only on write; renderer reads any cached bytes.
    import base64
    from pathlib import Path

    cache = Path("data/team_logos")
    # Use the real cache helper so the render path matches production.
    from hltv_bot import team_logos

    key = team_logos.logo_cache_key("https://img-cdn.hltv.org/teamlogo/g2-night.svg")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{key}.png"
    path.write_bytes(png)
    try:
        html = build_matches_html(
            [
                {
                    "id": "9",
                    "team1": "G2",
                    "team2": "Spirit",
                    "team1_logo": "https://img-cdn.hltv.org/teamlogo/g2-night.svg",
                    "team2_logo": "",
                    "event": "BLAST Premier",
                    "live": "0",
                    "stars": "5",
                    "time": "12:00",
                }
            ],
            tier_filter="T1",
        )
    finally:
        path.unlink(missing_ok=True)
    assert f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}" in html
    assert "team-badge" in html  # Spirit has no page logo


def test_events_html_date_omits_same_year():
    from datetime import datetime, timedelta, timezone
    from hltv_bot.render import build_events_html

    cst = timezone(timedelta(hours=8))
    start = int(datetime(2026, 10, 3, 12, tzinfo=cst).timestamp())
    end = int(datetime(2026, 10, 11, 12, tzinfo=cst).timestamp())
    html = build_events_html(
        [
            {
                "id": "1",
                "name": "ESL Pro League Season 24",
                "tier": "T1",
                "live": False,
                "start_ts": start,
                "end_ts": end,
                "days_left": 4,
                "location": "Malta",
                "prize": "$1",
            }
        ]
    )
    assert "10-03 ~ 10-11" in html
    assert "2026-10-03" not in html
    assert "ESL Pro League S24" in html


def test_matches_banner_uses_short_name_and_cached_event_logo(tmp_path, monkeypatch):
    from hltv_bot import events as events_mod
    from hltv_bot.render import build_matches_html

    monkeypatch.setattr(events_mod, "_LOGO_CACHE_DIR", tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    (tmp_path / "8057.png").write_bytes(png)
    html = build_matches_html(
        [
            {
                "id": "9",
                "team1": "MOUZ",
                "team2": "Spirit",
                "event": "StarLadder StarSeries Fall 2026",
                "event_id": "8057",
                "live": "0",
                "stars": "5",
                "time": "12:00",
            }
        ],
        tier_filter="T1",
    )
    assert "StarLadder StarSeries Fall 2026" not in html
    assert "StarLadder StarSeries Fall" in html
    assert "data:image/png;base64," in html


def test_events_empty_placeholder():
    from hltv_bot.render import build_events_html

    html = build_events_html([], tier_filter="Major / T1")
    assert 'class="empty-card"' in html
    assert "try /events t2" in html


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

    def send_chat_action(self, chat_id, action="upload_photo"):
        return {}

    def bot_can_delete_messages(self, chat_id, bot_user_id=None):
        return self.bot_permissions.get(int(chat_id), False)


def test_cmd_matches_downloads_only_visible_logos(monkeypatch):
    tg = _MockTg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "", path=None), admin_ids={1})
    rows = [
        {
            "id": "1",
            "team1": "G2",
            "team2": "Spirit",
            "event": "IEM Cologne",
            "event_id": "11",
            "event_logo": "https://img-cdn.hltv.org/eventlogo/iem.svg",
            "team1_logo": "https://img-cdn.hltv.org/teamlogo/g2.svg",
            "team2_logo": "https://img-cdn.hltv.org/teamlogo/spirit.svg",
            "live": "0",
            "stars": "5",
            "time": "12:00",
        },
        {
            "id": "2",
            "team1": "A",
            "team2": "B",
            "event": "Random Cup",
            "event_id": "22",
            "event_logo": "https://img-cdn.hltv.org/eventlogo/cup.svg",
            "team1_logo": "https://img-cdn.hltv.org/teamlogo/a.svg",
            "team2_logo": "",
            "live": "0",
            "stars": "1",
            "time": "13:00",
        },
    ]
    seen: dict[str, list] = {"teams": [], "events": []}
    monkeypatch.setattr("hltv_bot.bot.fetch_matches", lambda sess: rows)
    monkeypatch.setattr("hltv_bot.team_logos.ensure_team_logos", lambda urls: seen["teams"].extend(urls))
    monkeypatch.setattr("hltv_bot.events.ensure_event_logos", lambda pairs: seen["events"].extend(pairs))
    monkeypatch.setattr("hltv_bot.bot.render_matches_image", lambda *a, **k: b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)

    bot._cmd_matches(1, "")
    assert "https://img-cdn.hltv.org/teamlogo/g2.svg" in seen["teams"]
    assert "https://img-cdn.hltv.org/teamlogo/a.svg" not in seen["teams"]
    assert ("11", "https://img-cdn.hltv.org/eventlogo/iem.svg") in seen["events"]
    assert ("22", "https://img-cdn.hltv.org/eventlogo/cup.svg") not in seen["events"]


def test_events_image_cache_lasts_a_week():
    from hltv_bot.bot import EVENTS_IMG_CACHE_TTL, MATCHES_IMG_CACHE_TTL
    from hltv_bot.events import EVENTS_CACHE_TTL

    assert EVENTS_IMG_CACHE_TTL >= 7 * 24 * 3600
    assert EVENTS_CACHE_TTL >= 24 * 3600
    assert MATCHES_IMG_CACHE_TTL >= 6 * 3600


def test_cmd_events_cache_skips_logo_fetch(monkeypatch):
    from datetime import datetime, timedelta, timezone

    tg = _MockTg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "", path=None), admin_ids={1})
    start = int((datetime.now(timezone(timedelta(hours=8))) + timedelta(days=3)).timestamp())
    monkeypatch.setattr(
        "hltv_bot.bot.fetch_events",
        lambda sess: [
            {
                "id": "1",
                "name": "IEM Cologne 2026",
                "live": False,
                "start_ts": start,
                "end_ts": start + 86400,
                "logo_url": "https://img-cdn.hltv.org/eventlogo/iem.png",
                "country_code": "DE",
            }
        ],
    )
    calls = {"logos": 0, "flags": 0}
    monkeypatch.setattr("hltv_bot.events.ensure_event_logos", lambda pairs: calls.__setitem__("logos", calls["logos"] + 1))
    monkeypatch.setattr("hltv_bot.events.ensure_flags", lambda codes: calls.__setitem__("flags", calls["flags"] + 1))
    monkeypatch.setattr(
        "hltv_bot.bot.render_events_image",
        lambda *a, **k: b"\x89PNG\r\n\x1a\n" + b"\x00" * 32,
    )

    bot._cmd_events(1, "")
    bot._cmd_events(1, "")
    assert calls == {"logos": 1, "flags": 1}
    assert len(tg.photos) == 2


def test_cmd_matches_empty_sends_placeholder_photo(monkeypatch):
    tg = _MockTg()
    bot = HltvTelegramBot(tg, BrowserSession("chrome131", {}, "", path=None), admin_ids={1})
    monkeypatch.setattr("hltv_bot.bot.fetch_matches", lambda sess: [])
    bot._cmd_matches(1, "")
    assert len(tg.photos) == 1
    assert "暂无符合筛选的比赛" in tg.photos[0][2]
    assert len(tg.sent) == 0


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
