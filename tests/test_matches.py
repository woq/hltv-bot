from hltv_bot.live import format_log_item, merge_log, snapshot_from_scoreboard
from hltv_bot.matches import parse_match_list, parse_match_meta


def test_parse_match_list_dedupes():
    html = """
    <div class="liveMatch-container">
      <div class="matchRating">
        <i class="fa fa-star"></i><i class="fa fa-star"></i><i class="fa fa-star"></i>
      </div>
      <div class="matchTeamName">G2</div>
      <div class="matchTeamName">Spirit</div>
      <div class="matchEventName">BLAST Open Porto 2026</div>
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
    assert rows[1]["id"] == "111"
    assert rows[1]["live"] == "0"


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
            "ctPlayers": [{"nick": "donk", "kills": 10, "assists": 3, "deaths": 11, "adr": 65}],
            "tPlayers": [{"nick": "r1nkle", "kills": 19, "assists": 2, "deaths": 8, "adr": 91.3}],
        },
        meta={"url": "https://hltv.example/m", "team1": "G2", "team2": "Spirit"},
        log=log,
    )
    assert snap["scoreText"] == "13-6"
    assert snap["teams"][0]["players"][0]["nick"] == "donk"
