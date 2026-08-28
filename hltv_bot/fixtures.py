"""Static samples for UI testing (no HLTV requests)."""

from __future__ import annotations

import time
from typing import Any, Iterator

MOCK_MATCHES: list[dict[str, str]] = [
    {
        "id": "2396932",
        "team1": "G2",
        "team2": "Spirit",
        "event": "BLAST Open Porto 2026",
        "live": "1",
        "stars": "5",
        "url": "https://www.hltv.org/matches/2396932/g2-vs-spirit",
    },
    {
        "id": "2396933",
        "team1": "NaVi",
        "team2": "paiN",
        "event": "BLAST Open Porto 2026",
        "live": "0",
        "stars": "4",
        "url": "https://www.hltv.org/matches/2396933/navi-vs-pain",
    },
    {
        "id": "2396934",
        "team1": "M80",
        "team2": "FURIA",
        "event": "BLAST Open Porto 2026",
        "live": "0",
        "stars": "3",
        "url": "https://www.hltv.org/matches/2396934/m80-vs-furia",
    },
    {
        "id": "2397116",
        "team1": "The Huns",
        "team2": "Rare Atom",
        "event": "ESL Challenger League Season 52 Asia-Pacific Cup 1",
        "live": "1",
        "stars": "1",
        "url": "https://www.hltv.org/matches/2397116/x",
    },
    {
        "id": "2397226",
        "team1": "MISA",
        "team2": "ex-Mana",
        "event": "CCT 2026 Europe Series 8 Closed Qualifier",
        "live": "1",
        "stars": "0",
        "url": "https://www.hltv.org/matches/2397226/x",
    },
]


def mock_meta(list_id: str) -> dict[str, str | None]:
    for row in MOCK_MATCHES:
        if row["id"] == str(list_id):
            return {
                "url": row["url"],
                "scorebotId": row["id"],
                "scorebotUrl": "https://scorebot-lb.hltv.org",
                "team1": row["team1"],
                "team2": row["team2"],
            }
    return {
        "url": f"https://www.hltv.org/matches/{list_id}/demo",
        "scorebotId": str(list_id),
        "scorebotUrl": "https://scorebot-lb.hltv.org",
        "team1": "G2",
        "team2": "Spirit",
    }


def _board(ct: int, t: int, round_n: int) -> dict[str, Any]:
    return {
        "ctTeamName": "Spirit",
        "terroristTeamName": "G2",
        "ctScore": ct,
        "tScore": t,
        "currentRound": round_n,
        "mapName": "de_dust2",
        "ctPlayers": [
            {"nick": "donk", "kills": 10, "assists": 3, "deaths": 11, "adr": 65.0},
            {"nick": "sh1ro", "kills": 14, "assists": 1, "deaths": 8, "adr": 72.2},
            {"nick": "tN1R", "kills": 16, "assists": 1, "deaths": 12, "adr": 85.3},
        ],
        "tPlayers": [
            {"nick": "r1nkle", "kills": 19, "assists": 2, "deaths": 8, "adr": 91.3},
            {"nick": "huNter-", "kills": 5, "assists": 8, "deaths": 15, "adr": 51.9},
            {"nick": "NertZ", "kills": 10, "assists": 1, "deaths": 10, "adr": 55.8},
        ],
    }


def iter_mock_scorebot(list_id: str | int) -> Iterator[tuple[str, Any]]:
    """Yield a few scoreboard/log frames so /watch can exercise edit + 3K."""
    yield ("scoreboard", _board(12, 6, 18))
    yield (
        "log",
        {
            "log": [
                {"Kill": {"killerNick": "sh1ro", "victimNick": "huNter-", "weapon": "awp", "headShot": True}},
            ]
        },
    )
    time.sleep(1.2)
    yield (
        "log",
        {
            "log": [
                {"Kill": {"killerNick": "sh1ro", "victimNick": "NertZ", "weapon": "awp", "headShot": False}},
            ]
        },
    )
    time.sleep(1.2)
    yield (
        "log",
        {
            "log": [
                {"Kill": {"killerNick": "sh1ro", "victimNick": "r1nkle", "weapon": "awp", "headShot": True}},
                {"BombPlanted": {"playerNick": "donk", "bombSite": "A"}},
            ]
        },
    )
    time.sleep(1.2)
    yield ("scoreboard", _board(13, 6, 19))
    yield (
        "log",
        {
            "log": [
                {
                    "RoundEnd": {
                        "winner": "CT",
                        "winType": "CTs_Win",
                    }
                }
            ]
        },
    )
    while True:
        time.sleep(30)
        yield ("scoreboard", _board(13, 6, 19))
