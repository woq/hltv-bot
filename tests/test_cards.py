from hltv_bot.cards import _events_html, _matches_html, render_card


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
    html = _matches_html(card, 300, 416)
    assert "class='body mbody'" in html
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
