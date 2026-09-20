from hltv_bot.watch import LOG_EVENT_NAMES, ScorebotFeed, WatchState, apply_link_status, watch_fingerprint


def test_fulllog_is_a_log_event():
    assert "fullLog" in LOG_EVENT_NAMES
    assert "log" in LOG_EVENT_NAMES


def test_feed_applies_fulllog_like_log():
    feed = ScorebotFeed()
    payload = {
        "log": [
            {
                "Kill": {
                    "killerNick": "sh1ro",
                    "victimNick": "huNter-",
                    "weapon": "awp",
                    "headShot": True,
                    "eventId": 4,
                }
            }
        ]
    }
    assert feed.apply_log(payload) is True
    assert feed.log[0]["killer"] == "sh1ro"
    assert feed.apply_log(payload) is False
    wrapped = ScorebotFeed()
    assert wrapped.apply_log(payload["log"]) is True
    assert wrapped.log[0]["event_id"] == "4"


def test_feed_scoreboard_then_log_patches_score():
    feed = ScorebotFeed()
    feed.apply_scoreboard(
        {
            "ctTeamName": "Spirit",
            "terroristTeamName": "G2",
            "counterTerroristScore": 0,
            "terroristScore": 0,
            "currentRound": 1,
            "mapName": "de_mirage",
        }
    )
    feed.apply_log(
        {
            "log": [
                {
                    "RoundEnd": {
                        "winner": "TERRORIST",
                        "winType": "Target_Bombed",
                        "counterTerroristScore": 0,
                        "terroristScore": 1,
                    }
                }
            ]
        }
    )
    assert feed.board["terroristScore"] == 1
    assert feed.log[0]["type"] == "round_over_t"


def test_apply_link_status_clears_notice_when_connected():
    st = WatchState(list_id="1", meta={})
    apply_link_status(st, {"state": "reconnect", "detail": "ws close", "wait": 3, "transport": "chrome"})
    assert st.link == "reconnect"
    assert st.notice == "ws close"
    assert st.next_at > 0
    apply_link_status(st, {"state": "connected", "transport": "ws"})
    assert st.link == "connected"
    assert st.transport == "ws"
    assert st.notice == ""
    assert st.next_at == 0.0


def test_watch_fingerprint_debug_vs_live():
    snap = {"scoreText": "1-0", "roundText": "2 - Mirage", "log": [], "teams": [], "live": True}
    live = watch_fingerprint(snap, debug=False, link="connected", notice="", next_at=0)
    debug = watch_fingerprint(
        snap, debug=True, link="disconnected", notice="stale", next_at=0, trace_tail="ws close"
    )
    assert live != debug
    assert debug.startswith("debug|")
