from hltv_bot.format import format_match_list, format_rich_html, format_telegram
from hltv_bot.profile import pick_impersonate
from hltv_bot.scorebot import ready_for_match_payload, scorebot_base
from hltv_bot.snapshot import snapshot_fingerprint

SNAP = {
    "url": "https://www.hltv.org/matches/2396932/g2-vs-spirit",
    "live": True,
    "team1": {"name": "G2", "id": "5995"},
    "team2": {"name": "Spirit", "id": "7020"},
    "roundText": "19 - Dust2",
    "scoreText": "13-6",
    "ctScore": 13,
    "tScore": 6,
    "teams": [
        {
            "name": "Spirit",
            "players": [
                {"nick": "tN1R", "kills": 16, "assists": 1, "deaths": 12, "adr": 85.3}
            ],
        },
        {
            "name": "G2",
            "players": [
                {"nick": "r1nkle", "kills": 19, "assists": 2, "deaths": 8, "adr": 91.3}
            ],
        },
    ],
    "log": [
        {
            "type": "kill",
            "text": "sh1ro huNter-",
            "weapon": "awp",
            "headshot": False,
            "assist": False,
        },
        {"type": "round_over_ct", "text": "Round over - Winner: CT (6 - 13)"},
    ],
}


def test_format_contains_score_and_log():
    text = format_telegram(SNAP)
    assert "LIVE" in text
    assert "G2" in text and "Spirit" in text
    assert "13" in text and "6" in text
    assert "tN1R" in text
    assert "AWP" in text
    assert "killed" in text or "huNter-" in text
    assert "<pre>" in text
    snap_down = dict(SNAP)
    snap_down["link"] = "disconnected"
    assert "断开" in format_telegram(snap_down)
    rich = format_rich_html(SNAP)
    assert "<table" in rich and "<ul>" in rich and "<h3>" in rich
    assert "AWP" in rich


def test_format_multikill_banner():
    snap = dict(SNAP)
    snap["log"] = [
        {
            "type": "kill",
            "killer": "sh1ro",
            "victim": "a",
            "weapon": "awp",
            "headshot": True,
        },
        {"type": "kill", "killer": "sh1ro", "victim": "b", "weapon": "awp"},
        {"type": "kill", "killer": "sh1ro", "victim": "c", "weapon": "awp"},
    ]
    text = format_telegram(snap)
    assert "3K" in text
    assert "sh1ro" in text
    assert "Game log" in text


def test_match_list_rich_text():
    text = format_match_list(
        [
            {
                "id": "111",
                "team1": "A",
                "team2": "B",
                "event": "CCT",
                "live": "1",
                "stars": "1",
            },
            {
                "id": "2396932",
                "team1": "G2",
                "team2": "Spirit",
                "event": "BLAST Open Porto 2026",
                "live": "1",
                "stars": "5",
                "time": "21:00",
            },
            {
                "id": "2396933",
                "team1": "NaVi",
                "team2": "paiN",
                "event": "BLAST Open Porto 2026",
                "live": "0",
                "stars": "4",
            },
        ]
    )
    assert text.index("BLAST") < text.index("CCT")
    assert text.index("G2") < text.index("NaVi")
    assert "⭐⭐⭐⭐⭐" in text
    assert "/watch 2396932" in text
    assert text.count("BLAST Open Porto 2026") == 1
    assert "🔴" in text
    assert "21:00" in text
    hidden = format_match_list(
        [
            {
                "id": "9",
                "team1": "x",
                "team2": "y",
                "event": "low",
                "live": "1",
                "stars": "0",
            }
        ],
        starred_only=True,
    )
    assert "all" in hidden.lower()
    shown = format_match_list(
        [
            {
                "id": "9",
                "team1": "x",
                "team2": "y",
                "event": "low",
                "live": "1",
                "stars": "0",
            }
        ],
        starred_only=False,
    )
    assert "/watch 9" in shown


def test_html_escapes_nicks():
    snap = dict(SNAP)
    snap["team1"] = {"name": "A<B"}
    text = format_telegram(snap)
    assert "A&lt;B" in text
    assert "A<B" not in text


def test_fingerprint_changes_with_log():
    a = snapshot_fingerprint(SNAP)
    other = dict(SNAP)
    other["log"] = [{"text": "Round started"}]
    assert a != snapshot_fingerprint(other)


def test_ready_payload():
    assert ready_for_match_payload(2396932) == '{"token": "", "listId": "2396932"}'


def test_scorebot_base_picks_last_url():
    assert scorebot_base("https://a.example,https://scorebot-lb.hltv.org") == (
        "https://scorebot-lb.hltv.org"
    )


def test_pick_impersonate_returns_string():
    name = pick_impersonate("chrome131")
    assert isinstance(name, str) and name.startswith("chrome")
