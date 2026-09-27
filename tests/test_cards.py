from hltv_bot.cards import _events_html, _matches_html, render_card


def test_guide_card_explains_usage():
    from hltv_bot.cards import _guide_html

    html = _guide_html({"morning": 10, "evening": 20}, 760, 520)
    assert "hltv-bot" in html
    assert "10:00" in html and "20:00" in html
    assert "/follow" in html and "/cover" in html
    assert "/watch" in html and "/track" in html


def test_score_card_renders_bo1_and_current_map():
    from hltv_bot.cards import _match_html

    series = {
        "view": "match",
        "kind": "score",
        "label": "比分",
        "team1": "K27",
        "team2": "SINNERS",
        "pair": ("3", "5"),
        "event": "1win Private Club Season 1",
        "note": "当前图 · bo3",
        "clock": "09-27 20:00",
    }
    html = _match_html(series, 420, 520)
    assert "当前图 · bo3" in html
    assert "K27" in html and "SINNERS" in html
    assert ">3<" in html and ">5<" in html
    png = render_card(series)
    assert png.startswith(b"\x89PNG")

    bo1 = {**series, "team1": "DEPO", "team2": "PAQT", "pair": ("13", "9"), "note": "bo1"}
    html = _match_html(bo1, 420, 520)
    assert "bo1" in html
    assert "当前图" not in html
    assert render_card(bo1).startswith(b"\x89PNG")


def test_matches_card_html_and_render():
    card = {
        "view": "matches",
        "rows": [
            {
                "id": "2396932",
                "team1": "Spirit",
                "team2": "G2",
                "score1": "13",
                "score2": "9",
                "time": "20:00",
                "event": "IEM Cologne 2026",
                "stars": "5",
                "live": "1",
                "format": "bo3",
                "maps": "Nuke · Ancient · Mirage",
                "map_index": "0",
            },
            {
                "id": "2396933",
                "team1": "NaVi",
                "team2": "FaZe",
                "score1": "",
                "score2": "",
                "time": "22:30",
                "event": "IEM Cologne 2026",
                "stars": "4",
                "live": "0",
            },
        ],
    }
    html = _matches_html(card, 400, 416)
    assert html.count("class='mcard mbody'") == 2
    assert "mtag on" in html
    assert "mmap-now'>Nuke" in html
    assert "mmap-rest'>Ancient" in html
    assert "mmap-rest'>Mirage" in html
    assert "当前图" not in html
    assert "#2396932" in html
    assert "#2396933" in html
    assert "sc live" in html
    assert "sc soon" in html

    png = render_card(card)
    assert png.startswith(b"\x89PNG")


def test_events_card_html_and_render():
    card = {
        "view": "events",
        "rows": [
            {
                "id": "8050",
                "name": "PGL Major Singapore 2026",
                "tier": "Major",
                "flag": "🇸🇬",
                "location": "Singapore",
                "when": "10-15 – 10-28",
                "prize": "$1,250,000",
            },
        ],
    }
    html = _events_html(card, 200, 416)
    assert "PGL Major Singapore 2026" in html
    assert "$1,250,000" in html
    assert "Major" in html

    png = render_card(card)
    assert png.startswith(b"\x89PNG")
