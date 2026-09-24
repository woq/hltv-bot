from hltv_bot.matches import format_start_time, parse_match_list, parse_match_meta, pretty_name


def test_live_log_start_is_not_the_list_live_flag():
    from hltv_bot.matches import live_log_started

    assert live_log_started('<div class="countdown">Starting soon</div>') is False
    assert live_log_started('<div class="live-log"><div class="log-row">start</div></div>') is True
    assert live_log_started('<div class="scorebot">Round start</div>') is True
    assert live_log_started('{"text":"start"}') is True


def test_parse_match_board_streak_is_the_trailing_run():
    from hltv_bot.matches import parse_match_board

    def cells(wins: list[bool]) -> str:
        bits = []
        for won in wins:
            if won:
                bits.append('<img class="round-history-outcome" title="won">')
            else:
                bits.append('<div class="round-history-bar t empty"></div>')
        return "".join(bits)

    # G2 drops one, then takes five straight. Spirit is the other row.
    g2 = [False, True, True, True, True, True]
    spirit = [not x for x in g2]
    html = f"""
    <div class="mapholder">
      <div class="results-teamname">G2</div>
      <div class="results-team-score">6</div>
      <div class="mapname">Dust2</div>
      <div class="results-team-score">1</div>
      <div class="results-teamname">Spirit</div>
      <div class="round-history-team">{cells(g2)}</div>
      <div class="round-history-team">{cells(spirit)}</div>
    </div>
    """
    board = parse_match_board(html)
    assert board["map"] == "Dust2"
    assert board["map_score"] == "6-1"
    assert board["streak"] == 5
    assert board["streak_team"] == "G2"


def test_parse_match_list_reads_series_score():
    html = """
    <div class="liveMatch">
      <div class="matchTeam"><div class="matchTeamName">G2</div><div class="matchTeamScore">1</div></div>
      <div class="matchTeam"><div class="matchTeamName">Spirit</div><div class="matchTeamScore">0</div></div>
      <a href="/matches/2396932/g2-vs-spirit-blast">x</a>
    </div>
    """
    rows = parse_match_list(html)
    assert rows[0]["score1"] == "1"
    assert rows[0]["score2"] == "0"


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


def test_parse_match_list_placeholder_tbd():
    html = """
    <div class="upcomingMatch" data-stars="3">
      <div class="matchRating" data-stars="3"><i class="fa fa-star"></i><i class="fa fa-star"></i><i class="fa fa-star"></i></div>
      <a href="/matches/2398106/starladder-starseries-fall-2026-lower-bracket-final-starladder-starseries-fall-2026" class="match">
        <div class="matchEventName">StarLadder StarSeries Fall 2026</div>
      </a>
    </div>
    """
    rows = parse_match_list(html)
    assert len(rows) == 1
    assert rows[0]["team1"] == "TBD"
    assert rows[0]["team2"] == "TBD"
    assert rows[0]["title"] == "TBD vs TBD"
    assert "StarLadder" in rows[0]["event"]

    # When exclude_tbd is True
    rows_filtered = parse_match_list(html, exclude_tbd=True)
    assert len(rows_filtered) == 0


def test_parse_match_list_container_isolation():
    html = """
    <div class="upcomingMatch" data-stars="3">
      <div class="matchRating" data-stars="3"><i class="fa fa-star"></i><i class="fa fa-star"></i><i class="fa fa-star"></i></div>
      <div class="matchTime" data-unix="1787923200000">18:00</div>
      <a href="/matches/2398099/mouz-vs-natus-vincere-starladder-starseries-fall-2026" class="match">
        <div class="matchTeams">
          <div class="matchTeam"><div class="matchTeamName">MOUZ</div></div>
          <div class="matchTeam"><div class="matchTeamName">Natus Vincere</div></div>
        </div>
        <div class="matchEventName">StarLadder StarSeries Fall 2026</div>
      </a>
    </div>

    <div class="upcomingMatch" data-stars="0">
      <div class="matchTime" data-unix="1788009600000">01:00</div>
      <a href="/matches/2398106/starladder-starseries-fall-2026-lower-bracket-final-starladder-starseries-fall-2026" class="match">
        <div class="matchEventName">StarLadder StarSeries Fall 2026 Lower Bracket Final</div>
      </a>
    </div>

    <div class="upcomingMatch" data-stars="1">
      <div class="matchRating" data-stars="1"><i class="fa fa-star"></i></div>
      <div class="matchTime" data-unix="1788019600000">03:00</div>
      <a href="/matches/2398105/ryvex-vs-tbd-cct-season-3" class="match">
        <div class="matchTeams">
          <div class="matchTeam"><div class="matchTeamName">Ryvex</div></div>
        </div>
        <div class="matchEventName">CCT Season 3</div>
      </a>
    </div>
    """
    rows = parse_match_list(html)
    by_id = {r["id"]: r for r in rows}
    assert by_id["2398099"]["team1"] == "MOUZ"
    assert by_id["2398099"]["team2"] == "Natus Vincere"
    assert by_id["2398099"]["stars"] == "3"

    assert by_id["2398106"]["team1"] == "TBD"
    assert by_id["2398106"]["team2"] == "TBD"
    assert by_id["2398106"]["stars"] == "0"
    assert "Lower Bracket Final" in by_id["2398106"]["event"]

    assert by_id["2398105"]["team1"] == "Ryvex"
    assert by_id["2398105"]["team2"] == "Tbd"
    assert by_id["2398105"]["stars"] == "1"
    assert by_id["2398105"]["event"] == "CCT Season 3"


def test_parse_match_list_team_logos_prefer_night():
    html = """
    <div class="upcomingMatch" data-stars="2">
      <div class="matchTime" data-unix="1787923200000">18:00</div>
      <a href="/matches/2398200/mouz-vs-natus-vincere-starladder" class="match">
        <div class="matchTeams">
          <div class="matchTeam">
            <img alt="MOUZ" src="https://img-cdn.hltv.org/teamlogo/mouz-night.svg" class="matchTeamLogo night-only">
            <img alt="MOUZ" src="https://img-cdn.hltv.org/teamlogo/mouz-day.svg" class="matchTeamLogo day-only">
            <div class="matchTeamName">MOUZ</div>
          </div>
          <div class="matchTeam">
            <img alt="Natus Vincere" src="/img/static/team/placeholder.svg" class="matchTeamLogo night-only">
            <img alt="Natus Vincere" src="https://img-cdn.hltv.org/teamlogo/navi.svg?w=50" class="matchTeamLogo">
            <div class="matchTeamName">Natus Vincere</div>
          </div>
        </div>
      </a>
    </div>
    """
    rows = parse_match_list(html)
    assert rows[0]["team1_logo"] == "https://img-cdn.hltv.org/teamlogo/mouz-night.svg"
    assert rows[0]["team2_logo"] == "https://img-cdn.hltv.org/teamlogo/navi.svg?w=50"


def test_parse_match_list_event_logo():
    html = """
    <div class="upcomingMatch" data-stars="2">
      <a href="/matches/2398300/mouz-vs-spirit-starladder" class="match">
        <div class="matchTeams">
          <div class="matchTeamName">MOUZ</div>
          <div class="matchTeamName">Spirit</div>
        </div>
        <a href="/events/8057/starladder-fall" class="matchEvent">
          <img class="matchEventLogo night-only" src="https://img-cdn.hltv.org/eventlogo/sl-night.png" alt="">
          <img class="matchEventLogo day-only" src="https://img-cdn.hltv.org/eventlogo/sl-day.png" alt="">
          StarLadder StarSeries Fall 2026
        </a>
      </a>
    </div>
    """
    rows = parse_match_list(html)
    assert rows[0]["event_id"] == "8057"
    assert rows[0]["event_logo"] == "https://img-cdn.hltv.org/eventlogo/sl-night.png"


def test_parse_match_list_fallback_time_text():
    html = """
    <div class="upcomingMatch" data-stars="3">
      <div class="matchTime">19:30</div>
      <a href="/matches/2398102/vitality-vs-furia-blast-bounty" class="match">
        <div class="matchTeams">
          <div class="matchTeam"><div class="matchTeamName">Vitality</div></div>
          <div class="matchTeam"><div class="matchTeamName">FURIA</div></div>
        </div>
        <div class="matchEventName">BLAST Bounty</div>
      </a>
    </div>
    """
    rows = parse_match_list(html)
    assert len(rows) == 1
    assert rows[0]["id"] == "2398102"
    assert rows[0]["time"] == "19:30"
    assert rows[0]["team1"] == "Vitality"
    assert rows[0]["team2"] == "FURIA"


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


