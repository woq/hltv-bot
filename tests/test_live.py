from hltv_bot.live import (
    format_log_item,
    mark_new_round,
    mark_round_over,
    merge_log,
    merge_scoreboard,
    patch_board_from_log,
    snapshot_from_scoreboard,
)


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


def test_merge_log_skips_half_dump_with_new_event_ids():
    first_half = merge_log(
        [],
        {
            "log": [
                {
                    "Kill": {
                        "killerNick": "n1ssim",
                        "victimNick": "kyousuke",
                        "weapon": "ak47",
                        "headShot": True,
                        "eventId": 11,
                    }
                },
                {
                    "Kill": {
                        "killerNick": "latto",
                        "victimNick": "TeSeS",
                        "weapon": "ak47",
                        "headShot": False,
                        "eventId": 12,
                    }
                },
                {"RoundEnd": {"winner": "CT", "winType": "CTs_Win", "counterTerroristScore": 6, "terroristScore": 6}},
                {"RoundStart": {}},
            ]
        },
    )
    dump = {
        "log": [
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "ak47",
                    "headShot": True,
                    "eventId": 101,
                }
            },
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "ak47",
                    "headShot": True,
                    "eventId": 102,
                }
            },
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "ak47",
                    "headShot": True,
                    "eventId": 103,
                }
            },
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "ak47",
                    "headShot": True,
                    "eventId": 104,
                }
            },
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "ak47",
                    "headShot": True,
                    "eventId": 105,
                }
            },
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "ak47",
                    "headShot": True,
                    "eventId": 106,
                }
            },
            {
                "Kill": {
                    "killerNick": "n1ssim",
                    "victimNick": "kyousuke",
                    "weapon": "glock",
                    "headShot": False,
                    "eventId": 201,
                }
            },
            {
                "Kill": {
                    "killerNick": "m0NESY",
                    "victimNick": "n1ssim",
                    "weapon": "glock",
                    "headShot": True,
                    "eventId": 202,
                }
            },
            {
                "Kill": {
                    "killerNick": "m0NESY",
                    "victimNick": "latto",
                    "weapon": "glock",
                    "headShot": True,
                    "eventId": 203,
                }
            },
            {
                "Kill": {
                    "killerNick": "TeSeS",
                    "victimNick": "try",
                    "weapon": "glock",
                    "headShot": True,
                    "eventId": 204,
                }
            },
        ]
    }
    merged = merge_log(first_half, dump)
    ak = [x for x in merged if x.get("type") == "kill" and x.get("weapon") == "ak47" and x.get("killer") == "n1ssim"]
    glocks = [x for x in merged if x.get("type") == "kill" and x.get("weapon") == "glock"]
    assert len(ak) == 1
    assert len(glocks) == 4
    assert merged[0]["killer"] == "TeSeS"


def test_merge_log_dedupes_same_pair_in_round():
    raw = {
        "log": [
            {"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True}},
            {"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True}},
            {"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True}},
        ]
    }
    log = merge_log([], raw)
    assert len(log) == 1
    later = merge_log(
        [{"type": "round_start", "killer": "回合", "text": "开始", "detail": "开始"}] + log,
        {"log": [{"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True}}]},
    )
    assert later[0]["killer"] == "n1ssim"
    assert sum(1 for x in later if x.get("type") == "kill") == 2


def test_merge_log_keeps_kill_and_assist_burst():
    log = merge_log(
        [],
        {
            "log": [
                {"Kill": {"killerNick": "m0NESY", "victimNick": "arT", "weapon": "glock", "headShot": True, "eventId": 1}},
                {"Assist": {"assisterNick": "dumau", "victimNick": "arT", "killEventId": 1}},
            ]
        },
    )
    assert len(log) == 1
    assert log[0]["assister"] == "dumau"
    loose = merge_log(
        [],
        {
            "log": [
                {"Kill": {"killerNick": "m0NESY", "victimNick": "arT", "weapon": "glock", "headShot": True}},
                {"Assist": {"assisterNick": "dumau", "victimNick": "kyousuke"}},
            ]
        },
    )
    assert [x.get("type") for x in loose] == ["assist", "kill"]
    assert loose[0]["killer"] == "dumau"


def test_merge_log_live_burst_not_replayed_against_prior_round():
    prior = merge_log(
        [],
        {
            "log": [
                {"Kill": {"killerNick": "m0NESY", "victimNick": "arT", "weapon": "awp", "headShot": True, "eventId": 1}},
                {"Kill": {"killerNick": "TeSeS", "victimNick": "try", "weapon": "ak47", "headShot": False, "eventId": 2}},
            ]
        },
    )
    prior = [{"type": "round_start", "killer": "回合", "text": "开始", "detail": "开始"}] + prior
    live = merge_log(
        prior,
        {
            "log": [
                {"Kill": {"killerNick": "m0NESY", "victimNick": "arT", "weapon": "awp", "headShot": True, "eventId": 3}},
                {"Assist": {"assisterNick": "dumau", "victimNick": "arT"}},
                {"Kill": {"killerNick": "TeSeS", "victimNick": "try", "weapon": "ak47", "headShot": False, "eventId": 4}},
                {"Assist": {"assisterNick": "s1mple", "victimNick": "try"}},
            ]
        },
    )
    kills = [x for x in live if x.get("type") == "kill"]
    assert len(kills) == 4


def test_merge_log_allows_reused_event_id_after_round_start():
    first = merge_log(
        [],
        {"log": [{"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True, "eventId": 1}}]},
    )
    nxt = merge_log(
        [{"type": "round_start", "killer": "回合", "text": "开始", "detail": "开始"}] + first,
        {"log": [{"Kill": {"killerNick": "m0NESY", "victimNick": "arT", "weapon": "glock", "headShot": True, "eventId": 1}}]},
    )
    assert nxt[0]["killer"] == "m0NESY"
    assert sum(1 for x in nxt if x.get("type") == "kill") == 2


def test_merge_log_normalizes_descending_dump():
    # When scorebot sends full match dump, it sends newest first:
    # [Round 2 kill (eid 20), RoundEnd 1-0, Round 1 kill (eid 10)]
    dump = {
        "log": [
            {"Kill": {"killerNick": "m0NESY", "victimNick": "b1t", "weapon": "awp", "headShot": True, "eventId": 20}},
            {"RoundEnd": {"counterTerroristScore": 1, "terroristScore": 0, "winner": "CT", "winType": "CTs_Win"}},
            {"Kill": {"killerNick": "donk", "victimNick": "s1mple", "weapon": "ak47", "headShot": True, "eventId": 10}},
        ]
    }
    merged = merge_log([], dump)
    # merged[0] must be the latest event in the match (m0NESY kill in Round 2)
    assert merged[0]["killer"] == "m0NESY"
    assert merged[0]["event_id"] == "20"
    # merged[-1] should be the earliest event (donk kill in Round 1)
    assert merged[-1]["killer"] == "donk"
    assert merged[-1]["event_id"] == "10"



def test_mark_new_round_inserts_start():
    feed = [{"type": "kill", "killer": "a", "victim": "b", "weapon": "ak47"}]
    out, n = mark_new_round(feed, {"currentRound": 13}, 12)
    assert n == 13
    assert out[0]["type"] == "round_start"
    again, n2 = mark_new_round(out, {"currentRound": 13}, n)
    assert n2 == 13
    assert again[0]["type"] == "round_start"
    assert sum(1 for x in again if x.get("type") == "round_start") == 1
    mapped, n3 = mark_new_round(
        [{"type": "kill", "killer": "a", "victim": "b", "weapon": "ak47"}],
        {"currentRound": 1},
        24,
    )
    assert n3 == 1
    assert mapped[0]["type"] == "round_start"
    assert mapped[0]["text"] == "start"


def test_mark_round_over_inserts_when_score_ticks():
    feed, ct, t = mark_round_over([], {"counterTerroristScore": 4, "terroristScore": 2}, None, None)
    assert feed == []
    assert (ct, t) == (4, 2)
    nxt, ct2, t2 = mark_round_over(
        feed,
        {
            "counterTerroristScore": 5,
            "terroristScore": 2,
            "ctMatchHistory": {
                "firstHalf": [{"type": "CTs_Win", "roundOrdinal": 7, "survivingPlayers": 3}]
            },
        },
        ct,
        t,
    )
    assert (ct2, t2) == (5, 2)
    assert nxt[0]["type"] == "round_over_ct"
    assert "Round over" in nxt[0]["text"]
    assert "elimination" in nxt[0]["text"]
    again, _, _ = mark_round_over(nxt, {"counterTerroristScore": 5, "terroristScore": 2}, ct2, t2)
    assert sum(1 for x in again if str(x.get("type") or "").startswith("round_over")) == 1


def test_format_log_round_end_english():
    item = format_log_item(
        {
            "RoundEnd": {
                "winner": "TERRORIST",
                "winType": "Target_Bombed",
                "counterTerroristScore": 3,
                "terroristScore": 4,
            }
        }
    )
    assert item["type"] == "round_over_t"
    assert item["killer"] == "Round"
    assert "Round over" in item["text"]
    assert "bomb" in item["text"]
    assert item["ct_score"] == 3


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
    assert "planted" in item["detail"]
    assert "A" in item["detail"]


def test_merge_scoreboard_keeps_ahead_header():
    prev = {
        "mapName": "de_dust2",
        "currentRound": 6,
        "counterTerroristScore": 1,
        "terroristScore": 5,
        "ctMatchHistory": {"firstHalf": [{"type": "lost", "roundOrdinal": 1}]},
        "terroristMatchHistory": {"firstHalf": [{"type": "Target_Bombed", "roundOrdinal": 1}]},
        "CT": [],
    }
    incoming = {
        "mapName": "de_dust2",
        "currentRound": 1,
        "counterTerroristScore": 0,
        "terroristScore": 0,
        "currentRoundState": "warmup",
        "CT": [{"nick": "x", "score": 5, "deaths": 1}],
    }
    got = merge_scoreboard(prev, incoming)
    assert got["currentRound"] == 6
    assert got["terroristScore"] == 5
    assert got["CT"][0]["nick"] == "x"


def test_merge_log_fulllog_shape_same_as_log():
    payload = {
        "log": [
            {"Kill": {"killerNick": "sh1ro", "victimNick": "huNter-", "weapon": "awp", "headShot": True, "eventId": 7}},
        ]
    }
    a = merge_log([], payload)
    b = merge_log([], payload["log"])
    assert a[0]["killer"] == b[0]["killer"] == "sh1ro"
    assert a[0]["event_id"] == "7"


def test_merge_log_noop_returns_same_list():
    raw = {
        "log": [
            {"Kill": {"killerNick": "n1ssim", "victimNick": "kyousuke", "weapon": "ak47", "headShot": True, "eventId": 1}},
        ]
    }
    once = merge_log([], raw)
    twice = merge_log(once, raw)
    assert twice is once


def test_merge_log_assist_counts_as_change():
    kills = merge_log(
        [],
        {"log": [{"Kill": {"killerNick": "m0NESY", "victimNick": "arT", "weapon": "glock", "headShot": True, "eventId": 1}}]},
    )
    with_assist = merge_log(
        kills,
        {"log": [{"Assist": {"assisterNick": "dumau", "victimNick": "arT", "killEventId": 1}}]},
    )
    assert with_assist is not kills
    assert with_assist[0]["assister"] == "dumau"


