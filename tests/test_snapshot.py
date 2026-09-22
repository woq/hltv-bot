from hltv_bot.format import _alive_pair, format_rich_watch_card
from hltv_bot.live import snapshot_from_scoreboard
from hltv_bot.snapshot import snapshot_fingerprint, snapshot_log_fingerprint

# Live HLTV scoreboard: no ctScore/tScore/kills, freezePeriod, currentRound stuck.
LIVE_SCOREBOARD = {
    "TERRORIST": [
        {"nick": "huNter-", "alive": False, "deaths": 8, "assists": 2, "damagePrRound": 71.4},
        {"nick": "malbsMd", "alive": False, "deaths": 9, "assists": 1, "damagePrRound": 64.0},
        {"nick": "HeavyGod", "alive": False, "deaths": 7, "assists": 3, "damagePrRound": 80.2},
        {"nick": "SunPayus", "alive": False, "deaths": 6, "assists": 1, "damagePrRound": 55.1},
        {"nick": "HADES", "alive": False, "deaths": 8, "assists": 2, "damagePrRound": 68.8},
    ],
    "CT": [
        {"nick": "sh1ro", "alive": False, "deaths": 4, "assists": 2, "damagePrRound": 88.0, "score": 16},
        {"nick": "donk", "alive": False, "deaths": 5, "assists": 3, "damagePrRound": 95.2, "score": 19},
        {"nick": "zont1x", "alive": False, "deaths": 6, "assists": 4, "damagePrRound": 72.0},
        {"nick": "chopper", "alive": False, "deaths": 7, "assists": 2, "damagePrRound": 61.3},
        {"nick": "magixx", "alive": False, "deaths": 5, "assists": 1, "damagePrRound": 70.5},
    ],
    "ctMatchHistory": {
        "firstHalf": [
            {"type": "CTs_Win", "roundOrdinal": 1, "survivingPlayers": 3},
            {"type": "lost", "roundOrdinal": 2, "survivingPlayers": 0},
            {"type": "Bomb_Defused", "roundOrdinal": 3, "survivingPlayers": 2},
        ]
    },
    "terroristMatchHistory": {
        "firstHalf": [
            {"type": "lost", "roundOrdinal": 1, "survivingPlayers": 0},
            {"type": "Target_Bombed", "roundOrdinal": 2, "survivingPlayers": 2},
            {"type": "lost", "roundOrdinal": 3, "survivingPlayers": 0},
        ]
    },
    "bombPlanted": False,
    "mapName": "de_mirage",
    "terroristTeamName": "G2",
    "ctTeamName": "Spirit",
    "currentRound": 1,
    "counterTerroristScore": 8,
    "terroristScore": 11,
    "ctTeamScore": 8,
    "tTeamScore": 11,
    "currentRoundState": "freezePeriod",
    "frozen": False,
    "live": True,
}

def test_snapshot_reads_ct_team_score_keys():
    snap = snapshot_from_scoreboard(
        {
            "ctTeamName": "Legacy",
            "terroristTeamName": "Falcons",
            "ctTeamScore": 4,
            "tTeamScore": 2,
            "currentRound": 7,
            "mapName": "de_dust2",
        }
    )
    assert snap["scoreText"] == "4-2"
    assert snap["roundText"].startswith("7")


def test_snapshot_includes_round_history():
    snap = snapshot_from_scoreboard(
        {
            "ctTeamName": "Spirit",
            "terroristTeamName": "G2",
            "counterTerroristScore": 2,
            "terroristScore": 1,
            "currentRound": 4,
            "mapName": "de_dust2",
            "ctMatchHistory": {
                "firstHalf": [
                    {"type": "CTs_Win", "roundOrdinal": 1, "survivingPlayers": 3},
                    {"type": "lost", "roundOrdinal": 2, "survivingPlayers": 0},
                    {"type": "CTs_Win", "roundOrdinal": 3, "survivingPlayers": 2},
                ]
            },
            "terroristMatchHistory": {
                "firstHalf": [
                    {"type": "lost", "roundOrdinal": 1, "survivingPlayers": 0},
                    {"type": "Target_Bombed", "roundOrdinal": 2, "survivingPlayers": 2},
                    {"type": "lost", "roundOrdinal": 3, "survivingPlayers": 0},
                ]
            },
        }
    )
    assert [(x["n"], x["winner"]) for x in snap["history"]] == [
        (1, "CT"),
        (2, "T"),
        (3, "CT"),
    ]


def test_snapshot_round_from_history_when_current_round_stuck():
    snap = snapshot_from_scoreboard(
        {
            "ctTeamName": "MOUZ",
            "terroristTeamName": "NRG",
            "counterTerroristScore": 0,
            "terroristScore": 5,
            "currentRound": 1,
            "currentRoundState": "warmup",
            "frozen": True,
            "mapName": "de_dust2",
            "CT": [{"nick": "x", "score": 5, "deaths": 6, "assists": 1, "alive": False}],
            "TERRORIST": [{"nick": "y", "score": 8, "deaths": 2, "assists": 1, "alive": True}],
            "ctMatchHistory": {
                "firstHalf": [
                    {"type": "lost", "roundOrdinal": 1},
                    {"type": "lost", "roundOrdinal": 2},
                    {"type": "lost", "roundOrdinal": 3},
                    {"type": "lost", "roundOrdinal": 4},
                    {"type": "lost", "roundOrdinal": 5},
                ]
            },
            "terroristMatchHistory": {
                "firstHalf": [
                    {"type": "Target_Bombed", "roundOrdinal": 1},
                    {"type": "Target_Bombed", "roundOrdinal": 2},
                    {"type": "Target_Bombed", "roundOrdinal": 3},
                    {"type": "Target_Bombed", "roundOrdinal": 4},
                    {"type": "Terrorists_Win", "roundOrdinal": 5},
                ]
            },
        }
    )
    assert snap["scoreText"] == "0-5"
    assert snap["roundText"].startswith("6")
    assert snap["history"]
    assert snap["roundState"] == "live"
    assert snap["frozen"] is False
    assert snap["teams"][0]["players"][0]["kills"] == 5


def test_snapshot_warmup_overridden_when_round_or_score_advanced():
    # round > 1 but roundState left as warmup
    snap = snapshot_from_scoreboard(
        {
            "currentRound": 5,
            "currentRoundState": "warmup",
            "mapName": "de_ancient",
            "counterTerroristScore": 2,
            "terroristScore": 2,
        }
    )
    assert snap["roundState"] == "live"
    assert snap["frozen"] is False
    assert snap["scoreText"] == "2-2"


def test_live_scoreboard_keys_freeze_and_inferred_round():
    snap = snapshot_from_scoreboard(
        LIVE_SCOREBOARD,
        meta={"url": "https://www.hltv.org/matches/2398088/x", "team1": "G2", "team2": "Spirit"},
    )
    assert snap["scoreText"] == "8-11"
    assert snap["ctScore"] == 8
    assert snap["tScore"] == 11
    assert snap["teams"][0]["name"] == "Spirit"
    assert snap["teams"][1]["name"] == "G2"
    assert snap["roundText"].startswith("4")
    assert "Mirage" in snap["roundText"]
    assert snap["frozen"] is True
    assert snap["roundState"].lower().replace(" ", "") in {"freezeperiod", "freeze"}
    assert [(x["n"], x["winner"]) for x in snap["history"]] == [
        (1, "CT"),
        (2, "T"),
        (3, "CT"),
    ]
    by_nick = {p["nick"]: p for t in snap["teams"] for p in t["players"]}
    assert by_nick["sh1ro"]["kills"] == 16
    assert by_nick["zont1x"]["kills"] == 0
    assert by_nick["huNter-"]["alive"] is False
    assert _alive_pair(snap["teams"]) == ""

    html = format_rich_watch_card(snap)
    assert "Spirit" in html and "G2" in html
    assert "8" in html and "11" in html
    assert "freeze" in html
    assert "0v0" not in html
    assert "R4" in html
    assert "<h3>" not in html


def test_snapshot_fingerprint_includes_assister():
    snap1 = {
        "scoreText": "0-1",
        "roundText": "1 - Mirage",
        "live": True,
        "log": [
            {"type": "kill", "killer": "sh1ro", "victim": "huNter-", "text": "sh1ro huNter-", "weapon": "awp", "headshot": True},
            {"type": "round_start", "text": "start"},
        ],
    }
    snap2 = dict(snap1)
    snap2["log"] = [
        {**snap1["log"][0], "assister": "donk"},
        snap1["log"][1],
    ]
    assert snapshot_log_fingerprint(snap1) != snapshot_log_fingerprint(snap2)
    assert snapshot_fingerprint(snap1) != snapshot_fingerprint(snap2)


def test_alive_only_does_not_change_fingerprint():
    base = {
        "scoreText": "3-2",
        "roundText": "6 - Mirage",
        "live": True,
        "frozen": False,
        "bombPlanted": False,
        "log": [{"type": "kill", "killer": "donk", "victim": "huNter-", "text": "donk huNter-"}],
        "teams": [
            {"name": "Spirit", "players": [{"nick": "donk", "kills": 8, "assists": 1, "deaths": 2, "adr": 90, "alive": True}]},
            {"name": "G2", "players": [{"nick": "huNter-", "kills": 3, "assists": 0, "deaths": 4, "adr": 60, "alive": True}]},
        ],
    }
    dead = dict(base)
    dead["teams"] = [
        {"name": "Spirit", "players": [{"nick": "donk", "kills": 8, "assists": 1, "deaths": 2, "adr": 90, "alive": True}]},
        {"name": "G2", "players": [{"nick": "huNter-", "kills": 3, "assists": 0, "deaths": 4, "adr": 60, "alive": False}]},
    ]
    assert snapshot_fingerprint(base) == snapshot_fingerprint(dead)
    frozen = dict(base)
    frozen["frozen"] = True
    assert snapshot_fingerprint(base) != snapshot_fingerprint(frozen)


def test_adr_only_does_not_change_fingerprint():
    base = {
        "scoreText": "3-2",
        "teams": [
            {"name": "Spirit", "players": [{"nick": "donk", "kills": 8, "assists": 1, "deaths": 2, "adr": 70.1}]},
        ],
    }
    hotter = {
        "scoreText": "3-2",
        "teams": [
            {"name": "Spirit", "players": [{"nick": "donk", "kills": 8, "assists": 1, "deaths": 2, "adr": 90.4}]},
        ],
    }
    assert snapshot_fingerprint(base) == snapshot_fingerprint(hotter)


def test_log_fingerprint_matches_visible_card_rows():
    def row(i: int) -> dict:
        return {"type": "kill", "killer": f"p{i}", "victim": "x", "text": f"k{i}"}

    shown = {"log": [row(i) for i in range(10)]}
    extra = {"log": [row(i) for i in range(11)]}
    changed_tail = {"log": [row(i) for i in range(9)] + [row(99)]}
    assert snapshot_log_fingerprint(shown) == snapshot_log_fingerprint(extra)
    assert snapshot_log_fingerprint(shown) != snapshot_log_fingerprint(changed_tail)
