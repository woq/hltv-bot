from hltv_bot.fixtures import MOCK_MATCHES
from hltv_bot.render import classify_event_tier, tier_rank, render_matches_image, localize_team


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
