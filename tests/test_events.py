from datetime import datetime, timedelta, timezone
from hltv_bot.events import (
    classify_tier,
    filter_and_sort_events,
    format_events_html,
    parse_events_list,
)

CST = timezone(timedelta(hours=8))


def test_classify_tier():
    assert classify_tier("PGL CS2 Major Copenhagen 2024") == "Major"
    assert classify_tier("Perfect World Shanghai Major 2027") == "Major"
    assert classify_tier("ESL Pro League Season 24") == "T1"
    assert classify_tier("IEM Cologne 2026") == "T1"
    assert classify_tier("BLAST Rivals 2026 Season 2") == "T1"
    assert classify_tier("CCT 2026 Europe Series 9") == "T2"
    assert classify_tier("Thunderpick World Championship 2026") == "T2"
    assert classify_tier("StarLadder StarSeries Fall 2026") == "T2"
    assert classify_tier("Random Qualifier") == "T3"
    assert classify_tier("Local LAN Cup") == "Other"


def test_parse_events_list_and_dedup():
    html = """
    <div class="ongoing-events-holder">
      <div class="ongoing-event-holder">
        <a href="/events/8057/starladder-fall" class="a-reset ongoing-event">
          <div class="text-ellipsis">StarLadder StarSeries Fall 2026</div>
          <span data-unix="1789639200000"></span>
          <span data-unix="1789898400000"></span>
        </a>
      </div>
      <!-- Duplicate entry in ongoing -->
      <div class="ongoing-event-holder">
        <a href="/events/8057/starladder-fall" class="a-reset ongoing-event">
          <div class="text-ellipsis">StarLadder StarSeries Fall 2026</div>
          <span data-unix="1789639200000"></span>
          <span data-unix="1789898400000"></span>
        </a>
      </div>
    </div>
    <div class="big-events">
      <a href="/events/8244/esl-pro-league-season-24" class="a-reset standard-box big-event">
        <div class="big-event-name">ESL Pro League Season 24</div>
        <div class="big-event-location">Katowice, Poland</div>
        <div class="col-value" title="$1,000,000">$1,000,000</div>
        <span data-unix="1791021600000"></span>
        <span data-unix="1791712800000"></span>
      </a>
    </div>
    """
    events = parse_events_list(html)
    assert len(events) == 2
    by_id = {e["id"]: e for e in events}
    assert by_id["8057"]["name"] == "StarLadder StarSeries Fall 2026"
    assert by_id["8057"]["live"] is True
    assert by_id["8244"]["name"] == "ESL Pro League Season 24"
    assert by_id["8244"]["live"] is False
    assert by_id["8244"]["location"] == "Katowice, Poland"
    assert by_id["8244"]["prize"] == "$1,000,000"


def test_filter_and_sort_events():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=CST)
    events = [
        {
            "id": "1",
            "name": "Local Small Qualifier",
            "live": False,
            "start_ts": 1789639200,
            "end_ts": 1789898400,
        },
        {
            "id": "2",
            "name": "PGL Major Singapore 2026",
            "live": False,
            "start_ts": 1796295600,
            "end_ts": 1797159600,
        },
        {
            "id": "3",
            "name": "ESL Pro League Season 24",
            "live": False,
            "start_ts": 1791021600,
            "end_ts": 1791712800,
        },
        {
            "id": "4",
            "name": "StarLadder StarSeries Fall 2026",
            "live": True,
            "start_ts": 1789639200,
            "end_ts": 1789898400,
        },
    ]
    filtered = filter_and_sort_events(events, now=now)
    assert len(filtered) == 2
    # Sooner event: EPL 24 (Oct 2026) before Major (Dec 2026)
    assert filtered[0]["id"] == "3"
    assert filtered[0]["tier"] == "T1"
    assert filtered[0]["days_left"] > 0

    assert filtered[1]["id"] == "2"
    assert filtered[1]["tier"] == "Major"
    assert filtered[1]["days_left"] > filtered[0]["days_left"]


def test_format_event_date_range_omits_year_unless_cross_year():
    from hltv_bot.events import format_event_date_range

    now = datetime(2026, 9, 18, 12, tzinfo=CST)
    same_start = int(datetime(2026, 10, 3, 12, tzinfo=CST).timestamp())
    same_end = int(datetime(2026, 10, 11, 12, tzinfo=CST).timestamp())
    assert format_event_date_range(same_start, same_end, now=now) == "10-03 ~ 10-11"
    assert format_event_date_range(same_start, 0, now=now) == "10-03"

    next_start = int(datetime(2027, 1, 10, 12, tzinfo=CST).timestamp())
    next_end = int(datetime(2027, 1, 20, 12, tzinfo=CST).timestamp())
    assert format_event_date_range(next_start, next_end, now=now) == "2027-01-10 ~ 2027-01-20"
    assert format_event_date_range(next_start, 0, now=now) == "2027-01-10"

    cross_start = int(datetime(2026, 12, 28, 12, tzinfo=CST).timestamp())
    cross_end = int(datetime(2027, 1, 4, 12, tzinfo=CST).timestamp())
    assert format_event_date_range(cross_start, cross_end, now=now) == "2026-12-28 ~ 2027-01-04"
    assert format_event_date_range(0, 0, pending="待定", now=now) == "待定"

    html = format_events_html(
        [
            {
                "name": "Same Year Cup",
                "tier": "T1",
                "live": False,
                "start_ts": same_start,
                "end_ts": same_end,
                "days_left": 3,
            }
        ]
    )
    assert "10-03 ~ 10-11" in html
    assert "2026-10-03" not in html


def test_ensure_event_logos_and_flags(monkeypatch, tmp_path):
    from hltv_bot import events as events_mod

    logos = tmp_path / "logos"
    flags = tmp_path / "flags"
    monkeypatch.setattr(events_mod, "_LOGO_CACHE_DIR", logos)
    monkeypatch.setattr(events_mod, "_FLAGS_CACHE_DIR", flags)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    gif = b"GIF89a" + b"\x00" * 48

    def fake_download(urls):
        out = {}
        for url in urls:
            out[url] = gif if url.endswith(".gif") else png
        return out

    monkeypatch.setattr("hltv_bot.team_logos.download_images", fake_download)
    events_mod.ensure_event_logos([("8057", "https://img-cdn.hltv.org/eventlogo/sl.png"), ("8057", "https://img-cdn.hltv.org/eventlogo/sl.png")])
    events_mod.ensure_flags(["pl", "PL"])
    assert (logos / "8057.png").is_file()
    assert (flags / "PL.gif").is_file()
    assert events_mod.get_cached_logo_data_uri("8057").startswith("data:image/png;base64,")
    assert "flag-img" in events_mod.get_flag_img_html("PL")


def test_format_events_html():
    events = [
        {
            "id": "2",
            "name": "PGL Major Singapore 2026",
            "tier": "Major",
            "live": False,
            "start_ts": 1796295600,
            "end_ts": 1797159600,
            "location": "Singapore",
            "prize": "$1,250,000",
            "days_left": 76,
        },
        {
            "id": "3",
            "name": "ESL Pro League Season 24",
            "tier": "T1",
            "live": False,
            "start_ts": 1791021600,
            "end_ts": 1791712800,
            "location": "Katowice, Poland",
            "prize": "$1,000,000",
            "days_left": 15,
        },
    ]
    html = format_events_html(events)
    assert "<b>近期赛事</b>" in html
    assert "<b>PGL Major Singapore 2026</b>" in html
    assert "<b>ESL Pro League Season 24</b>" in html
    assert "<b>还有 15 天开赛</b>" in html
    assert "Katowice, Poland" in html
    assert "$1,000,000" in html


def test_country_code_to_emoji_and_format_location():
    from hltv_bot.events import country_code_to_emoji, format_location, clean_event_display_name

    assert country_code_to_emoji("PL") == "🇵🇱"
    assert country_code_to_emoji("RO") == "🇷🇴"
    assert country_code_to_emoji("CN") == "🇨🇳"
    assert country_code_to_emoji("EU") == "🇪🇺"
    assert country_code_to_emoji("WORLD") == "🌐"
    assert country_code_to_emoji("") == ""

    assert "Katowice" in format_location("Katowice, Poland", "PL")
    assert "Malta" in format_location("Malta", "MT")
    assert "Sheffield" in format_location("Sheffield, United Kingdom |", "GB")
    assert format_location("", "") == "-"

    assert clean_event_display_name("ESL Pro League Season 24") == "ESL Pro League S24"
    assert clean_event_display_name("PGL Major Singapore 2026 Stage 1") == "PGL Major Singapore Stage 1"
    assert clean_event_display_name("IEM Beijing 2026") == "IEM Beijing"


def test_filter_and_sort_events_3_months():
    now = datetime(2026, 9, 18, 12, 0, tzinfo=CST)
    events = [
        {
            "id": "1",
            "name": "BLAST Event 2027",
            "live": False,
            "start_ts": 1789639200 + 120 * 86400,  # 120 days out
            "end_ts": 1789639200 + 125 * 86400,
        },
        {
            "id": "2",
            "name": "PGL Major Singapore 2026",
            "live": False,
            "start_ts": 1796295600,  # ~76 days out
            "end_ts": 1797159600,
        },
    ]
    # Filter with max_days=92 (3 months)
    filtered = filter_and_sort_events(events, allowed_tiers=("Major", "T1"), max_days=92, now=now)
    assert len(filtered) == 1
    assert filtered[0]["id"] == "2"

    # Filter with max_days=None includes further events
    filtered_all = filter_and_sort_events(events, allowed_tiers=("Major", "T1"), max_days=None, now=now)
    assert len(filtered_all) == 2


def test_classify_event_tier():
    from hltv_bot.events import classify_event_tier

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
    from hltv_bot.events import tier_rank

    assert tier_rank("T1") < tier_rank("T2")
    assert tier_rank("T2") < tier_rank("T3")
    assert tier_rank("T3") < tier_rank("Other")

