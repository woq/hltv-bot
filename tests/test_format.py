from hltv_bot.format import (
    format_match_list,
    format_match_list_rich,
    format_rich_html,
    format_telegram,
    format_watch_debug_html,
)
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
    assert "disconnected" in format_telegram(snap_down)
    rich = format_rich_html(SNAP)
    assert "<table" in rich
    assert "<h3>" not in rich
    assert "<ul>" not in rich
    assert "<footer>" not in rich
    assert "AWP" in rich
    assert rich.count("<table") >= 3
    assert "<mark>CT</mark>" in rich
    assert "<b>T</b>" in rich
    assert "<aside>" not in rich
    assert rich.startswith("<details>")
    assert "<summary>Stats" in rich
    assert rich.index("<details>") < rich.index("killed")
    assert "connected" in rich
    assert "R19" in rich


def test_scoreboard_notice_and_next_clock():
    from hltv_bot.format import format_next_clock

    snap = dict(SNAP)
    snap["link"] = "reconnect"
    snap["notice"] = "HTTP 502"
    snap["next_at"] = 1_783_000_000
    rich = format_rich_html(snap)
    assert "HTTP 502" in rich
    assert "next" in rich
    assert format_next_clock(1_783_000_000)
    assert "reconnect" in rich
    assert rich.rfind("reconnect") > rich.find("</table>")


def test_status_line_packs_match_bits():
    from hltv_bot.format import _status_line

    snap = dict(SNAP)
    snap["frozen"] = True
    snap["bombPlanted"] = True
    snap["teams"] = [
        {
            "name": "Spirit",
            "players": [
                {"nick": "a", "kills": 1, "assists": 0, "deaths": 0, "adr": 1, "alive": True},
                {"nick": "b", "kills": 0, "assists": 0, "deaths": 1, "adr": 1, "alive": False},
            ],
        },
        {
            "name": "G2",
            "players": [
                {"nick": "c", "kills": 1, "assists": 0, "deaths": 0, "adr": 1, "alive": True},
                {"nick": "d", "kills": 1, "assists": 0, "deaths": 0, "adr": 1, "alive": True},
            ],
        },
    ]
    snap["transport"] = "poll"
    line = _status_line("connected", "", None, snap=snap)
    assert "connected" in line
    assert "poll" in line
    assert "freeze" in line
    assert "bomb" in line
    assert "1v2" in line
    assert "R19" in line
    visible = line.replace("<p><i>", "").replace("</i></p>", "")
    assert len(visible) <= 68


def test_watch_debug_card_is_traces_not_scoreboard():
    html = format_watch_debug_html(
        team1="G2",
        team2="Spirit",
        list_id="2396932",
        link="reconnect",
        notice="HTTP 502",
        lines=["12:00:01 handshake HTTP 502", "12:00:20 error retry 25s"],
    )
    assert "<caption>DEBUG</caption>" in html
    assert "<pre>" in html
    assert "handshake HTTP 502" in html
    assert "0-0" not in html
    assert "cf_clearance" not in html
    assert "reconnect" in html
    assert "/watch 2396932" in html


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
    rich = format_rich_html(snap)
    assert "<mark>3K</mark>" in rich
    assert "sh1ro" in rich
    assert "<aside>" not in rich


def test_log_bomb_and_round_are_two_columns():
    snap = dict(SNAP)
    snap["log"] = [
        {"type": "bomb", "killer": "donk", "text": "planted A", "detail": "planted A"},
        {
            "type": "round_over_ct",
            "killer": "Round",
            "text": "Round over · CT · elimination",
            "detail": "Round over · CT · elimination",
        },
        {"type": "round_start", "killer": "Round", "text": "start", "detail": "start"},
        {"type": "assist", "killer": "huNter-", "victim": "donk", "detail": "assist donk"},
    ]
    rich = format_rich_html(snap)
    assert "<td><b>donk</b></td><td>planted A</td>" in rich
    assert "<td><b>Round</b></td>" in rich
    assert "Round over · CT · elimination" in rich
    assert "<td><b>Round</b></td><td><b>start</b></td>" in rich
    assert "<td><b>huNter-</b></td><td>assist donk</td>" in rich
    assert ">Who<" not in rich
    assert "回合" not in rich
    plus = dict(SNAP)
    plus["log"] = [
        {
            "type": "kill",
            "killer": "sh1ro",
            "victim": "donk",
            "weapon": "awp",
            "event_id": "9",
            "assister": "huNter-",
        }
    ]
    plus_rich = format_rich_html(plus)
    assert "+ huNter-" in plus_rich
    assert "killed donk" in plus_rich


def test_stats_collapsed_and_history_on_top():
    snap = dict(SNAP)
    snap["history"] = [
        {"n": 1, "winner": "CT", "winType": "CTs_Win"},
        {"n": 2, "winner": "T", "winType": "Target_Bombed"},
    ]
    rich = format_rich_html(snap)
    assert rich.startswith("<details>")
    assert "R1 CT elim" in rich
    assert "R2 T bomb" in rich
    assert rich.index("<details>") < rich.index("<table bordered compact>")
    assert rich.rfind("<p><i>") > rich.rfind("<table")


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
    rich_list = format_match_list_rich(
        [
            {
                "id": "2396932",
                "team1": "G2",
                "team2": "Spirit",
                "event": "BLAST Open Porto 2026",
                "live": "1",
                "stars": "5",
                "time": "21:00",
            }
        ]
    )
    assert "<table" in rich_list
    assert "<mark>LIVE</mark>" in rich_list
    assert "/watch 2396932" in rich_list
    assert "<h4>" in rich_list


def test_html_escapes_nicks():
    snap = dict(SNAP)
    snap["teams"] = [
        {
            "name": "A<B",
            "players": [{"nick": "x<y", "kills": 1, "assists": 0, "deaths": 0, "adr": 1}],
        },
        SNAP["teams"][1],
    ]
    text = format_telegram(snap)
    assert "A&lt;B" in text
    assert "A<B" not in text
    rich = format_rich_html(snap)
    assert "A&lt;B" in rich
    assert "x&lt;y" in rich
    assert "A<B" not in rich


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


def test_format_kv_table_standard_html():
    from hltv_bot.format import format_kv_table

    out = format_kv_table("Status", [("a", "1"), ("b", "2")])
    assert "<b>Status</b>" in out
    assert "• <b>a</b>: 1" in out
    assert "• <b>b</b>: 2" in out
    for tag in ("<h3>", "<table", "<tr>", "<td>", "<th>"):
        assert tag not in out
