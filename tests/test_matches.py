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


