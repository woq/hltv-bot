from hltv_bot.cards import _events_html, _matches_html, render_card


def test_event_card_is_title_then_countdown():
    from hltv_bot.cards import _event_html

    html = _event_html(
        {
            "view": "event",
            "tier": "T1",
            "name": "ESL Pro League Season 24",
            "flag": "🇩🇪",
            "location": "Cologne",
            "clock": "10-03 18:00",
            "remain": "还有 1 天 9 小时",
        },
        420,
        520,
    )
    assert html.index("ESL Pro League Season 24") < html.index("还有 1 天 9 小时") < html.index("class='foot'")
    assert "10-03 18:00" in html[html.index("class='foot'"):]
    assert "Cologne" in html[html.index("class='foot'"):]
    assert "Tier" not in html
    assert ">赛事<" not in html


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
    assert "class='stamp'" in html and "UTC+8" in html
    assert "tier-t1" in html
    assert "event-copy" in html
    assert "K27" in html and "SINNERS" in html
    assert ">3<" in html and ">5<" in html
    png = render_card(series)
    assert png.startswith(b"\x89PNG")

    bo1 = {**series, "team1": "DEPO", "team2": "PAQT", "pair": ("13", "9"), "note": "bo1"}
    html = _match_html(bo1, 420, 520)
    assert "bo1" in html
    assert "当前图" not in html
    assert render_card(bo1).startswith(b"\x89PNG")


def test_winner_card_puts_name_then_score_and_map_logos():
    from hltv_bot.cards import _match_html

    card = {
        "view": "match",
        "kind": "map",
        "label": "Map winner",
        "winner": 1,
        "team1": "Lynn Vision",
        "team2": "NEXVOID",
        "pair": ("13", "11"),
        "event": "ESL Challenger League",
        "map_rows": [
            {"name": "Ancient", "winner": 1, "current": True, "team_id": "8840", "logo": ""},
            {"name": "Nuke", "winner": 0, "current": False},
            {"name": "Inferno", "winner": 0, "current": False},
        ],
    }
    html = _match_html(card, 560, 520)
    body = html.split("</style>", 1)[-1]
    assert body.index("Map winner") < body.index("Lynn Vision") < body.index("class='hero-score'")
    assert html.index("Ancient") < html.index("Nuke") < html.index("Inferno")
    assert "mplogo" in html
    assert "系列" not in html
    assert "赛程页不标这一半" not in html

    live = {
        "view": "match",
        "kind": "score",
        "label": "比分",
        "team1": "Lynn Vision",
        "team2": "NEXVOID",
        "pair": ("6", "5"),
        "event": "ESL Challenger League",
        "map_rows": card["map_rows"],
    }
    live_html = _match_html(live, 520, 520)
    assert "赛程页不标这一半" not in live_html
    assert "Counter-Terrorist" not in live_html
    assert "Terrorist" not in live_html
    assert "name ct" not in live_html and "name t" not in live_html


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
    assert "mgrid" not in html.split("</style>", 1)[-1]


def test_eight_matches_use_two_columns():
    rows = [
        {
            "id": str(i),
            "team1": f"Team{i}A",
            "team2": f"Team{i}B",
            "time": f"{17 + i // 2}:00",
            "event": "ESL Pro League Season 24",
            "stars": "1",
            "live": "0",
        }
        for i in range(8)
    ]
    html = _matches_html({"view": "matches", "title": "赛程  10:00  ·  UTC+8", "rows": rows}, 800, 416)
    assert html.count("<table class='mgrid'>") == 1
    assert html.count("<tr>") == 4
    assert html.count("class='mcard mbody'") == 8
    body = html.split("</style>", 1)[-1]
    assert "ESL Pro League Season 24" in body
    assert "event-chip" not in body
    odd = [dict(row) for row in rows[:5]]
    odd[0]["event"] = "BLAST Premier"
    mixed = _matches_html({"view": "matches", "rows": odd}, 800, 416)
    assert mixed.count("<tr>") == 3
    assert mixed.count("<td></td>") == 1
    assert "mevent" in mixed


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
    assert "tier-major" in html
    assert "event-row" in html
    assert "Singapore" in html

    png = render_card(card)
    assert png.startswith(b"\x89PNG")


def test_match_winner_card_with_large_svg_logo_single_page():
    import base64
    import weasyprint
    import pypdfium2
    from hltv_bot.cards import _match_html, render_card

    svg_data = '<svg xmlns="http://www.w3.org/2000/svg" width="800px" height="800px" viewBox="0 0 100 100"><circle cx="50" cy="50" r="40" fill="red"/></svg>'
    b64_svg = f"data:image/svg+xml;base64,{base64.b64encode(svg_data.encode()).decode()}"
    card = {
        "view": "match",
        "kind": "match",
        "label": "Match winner",
        "team1": "9z",
        "team2": "TYLOO",
        "logo1": "",
        "logo2": b64_svg,
        "pair": ("2", "0"),
        "winner": 1,
        "map_rows": [
            {"name": "Nuke", "winner": 1, "score": "13-10", "loser_logo": b64_svg},
            {"name": "Mirage", "winner": 1, "score": "13-2", "loser_logo": b64_svg},
            {"name": "Inferno", "winner": 0, "score": ""},
        ],
        "map_score": "本图 13–2",
        "event": "ESL Pro League Season 24",
    }
    html = _match_html(card, 480, 420)
    assert f'<img class="m-logo" src="{b64_svg}"' in html
    pdf = weasyprint.HTML(string=html).write_pdf()
    doc = pypdfium2.PdfDocument(pdf)
    assert len(doc) == 1
    png = render_card(card)
    assert png.startswith(b"\x89PNG")

