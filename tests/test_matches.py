from hltv_bot.live import format_log_item, merge_log, patch_board_from_log, snapshot_from_scoreboard
from hltv_bot.matches import format_start_time, parse_match_list, parse_match_meta, pretty_name


def test_parse_match_list_dedupes():
    html = """
    <div class="liveMatch-container">
      <div class="matchRating">
        <i class="fa fa-star"></i><i class="fa fa-star"></i><i class="fa fa-star"></i>
      </div>
      <div class="matchTeamName">G2</div>
      <div class="matchTeamName">Spirit</div>
      <div class="matchEventName">BLAST Open Porto 2026</div>
      <div data-unix="1787923200000"></div>
      <a href="/matches/2396932/g2-vs-spirit-blast-open-porto-2026">x</a>
    </div>
    <a href="/matches/2396932/g2-vs-spirit-blast-open-porto-2026">again</a>
    <div class="upcomingMatch"><a href="/matches/111/foo-vs-bar-cct-2026">y</a></div>
    """
    rows = parse_match_list(html)
    assert rows[0]["id"] == "2396932"
    assert rows[0]["live"] == "1"
    assert rows[0]["stars"] == "3"
    assert rows[0]["team1"] == "G2"
    assert rows[0]["event"] == "BLAST Open Porto 2026"
    assert rows[0]["time"]
    assert rows[1]["id"] == "111"
    assert rows[1]["live"] == "0"


def test_format_start_time_clock():
    import re

    assert re.search(r"\d{2}:\d{2}", format_start_time(1787923200))
    assert re.search(r"\d{2}:\d{2}", format_start_time(1787923200000))


def test_pretty_name_acronyms():
    assert pretty_name("natus vincere") == "Natus Vincere"
    assert pretty_name("g2") == "G2"
    assert pretty_name("cct 2026 europe series 8") == "CCT 2026 Europe Series 8"
    assert pretty_name("G2") == "G2"


def test_parse_match_meta():
    html = """
    <div id="scoreboardElement" data-scorebot-url="https://scorebot-lb.hltv.org"
      data-scorebot-id="2396932" data-team1-name="G2" data-team2-name="Spirit"></div>
    """
    meta = parse_match_meta(html, url="https://www.hltv.org/matches/2396932/x")
    assert meta["scorebotId"] == "2396932"
    assert meta["team1"] == "G2"


def test_kill_log_and_snapshot():
    log = merge_log(
        [],
        {"log": [{"Kill": {"killerNick": "sh1ro", "victimNick": "huNter-", "weapon": "awp", "headShot": True}}]},
    )
    assert log[0]["weapon"] == "awp"
    assert log[0]["headshot"] is True
    assert log[0]["killer"] == "sh1ro"
    snap = snapshot_from_scoreboard(
        {
            "ctTeamName": "Spirit",
            "terroristTeamName": "G2",
            "ctScore": 13,
            "tScore": 6,
            "currentRound": 19,
            "mapName": "de_dust2",
            "ctTeam": [{"name": "donk", "score": 10, "assists": 3, "deaths": 11, "damagePrRound": 65}],
            "terroristTeam": [{"name": "r1nkle", "score": 19, "assists": 2, "deaths": 8, "damagePrRound": 91.3}],
        },
        meta={"url": "https://hltv.example/m", "team1": "G2", "team2": "Spirit"},
        log=log,
    )
    assert snap["scoreText"] == "13-6"
    assert snap["teams"][0]["players"][0]["nick"] == "donk"


def test_merge_log_skips_reconnect_replay():
    raw = {
        "log": [
            {"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True, "eventId": 1}},
            {"Kill": {"killerNick": "latto", "victimNick": "kyousuke", "weapon": "deagle", "headShot": False, "eventId": 2}},
        ]
    }
    once = merge_log([], raw)
    twice = merge_log(once, raw)
    assert len(once) == 2
    assert twice == once
    third = merge_log(
        twice,
        {"log": [{"Kill": {"killerNick": "n1ssim", "victimNick": "x", "weapon": "ak47", "headShot": True, "eventId": 3}}]},
    )
    assert len(third) == 3
    assert third[0]["killer"] == "n1ssim"
    assert third[0]["event_id"] == "3"


def test_patch_board_uses_last_round_end_score():
    board = patch_board_from_log(
        {"currentRound": 3, "ctTeamScore": 1, "tTeamScore": 1},
        {
            "log": [
                {
                    "RoundEnd": {
                        "winner": "CT",
                        "winType": "CTs_Win",
                        "counterTerroristScore": 2,
                        "terroristScore": 1,
                    }
                }
            ]
        },
    )
    assert board["counterTerroristScore"] == 2
    assert board["terroristScore"] == 1
    assert board["currentRound"] == 3


def test_format_log_bomb_has_nick_column():
    item = format_log_item(
        {"BombPlanted": {"playerNick": "donk", "bombSite": "A"}}
    )
    assert item["killer"] == "donk"
    assert "安包" in item["detail"]
    assert "A" in item["detail"]


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
