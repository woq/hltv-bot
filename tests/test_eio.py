from hltv_bot.eio import decode_payload, encode_event, parse_event, parse_open
from hltv_bot.scorebot import (
    POLL_EMPTY_GAP,
    POLL_MIN_GAP,
    RECONNECT_5XX,
    RECONNECT_MAX,
    RECONNECT_MIN,
    _is_http_error,
    _is_timeout,
    next_backoff,
    poll_gap,
    reconnect_wait,
)


def test_decode_open_packet():
    from hltv_bot.eio import encode_payload

    raw = encode_payload(
        '0{"sid":"abc","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":60000}'
    )
    pkts = decode_payload(raw)
    assert pkts[0].startswith("0{")
    opened = parse_open(pkts[0])
    assert opened["sid"] == "abc"
    assert "websocket" in opened["upgrades"]


def test_parse_log_event():
    pkt = '42["log","{\\"log\\":[{\\"Kill\\":{\\"killerNick\\":\\"donk\\"}}]}"]'
    ev = parse_event(pkt)
    assert ev is not None
    name, payload = ev
    assert name == "log"
    assert payload["log"][0]["Kill"]["killerNick"] == "donk"


def test_curl_28_is_timeout():
    assert _is_timeout(RuntimeError("curl: (28) Operation timed out after 30002 milliseconds"))


def test_encode_ready():
    s = encode_event("readyForMatch", '{"token":"","listId":"2396932"}')
    assert s.startswith("42[")
    assert "readyForMatch" in s
    assert "2396932" in s


def test_reconnect_wait_never_below_floor():
    import random

    random.seed(0)
    w = reconnect_wait(0)
    assert w >= RECONNECT_MIN
    w5 = reconnect_wait(1, http_5xx=True)
    assert w5 >= RECONNECT_MIN
    assert w5 >= RECONNECT_5XX * 0.85
    assert reconnect_wait(9999) <= RECONNECT_MAX


def test_next_backoff_doubles_and_caps():
    assert next_backoff(0) >= RECONNECT_MIN
    a = next_backoff(RECONNECT_MIN)
    assert a == RECONNECT_MIN * 2
    assert next_backoff(RECONNECT_MAX) == RECONNECT_MAX
    assert next_backoff(10, http_5xx=True) >= RECONNECT_5XX


def test_http_502_is_http_error():
    assert _is_http_error(RuntimeError("scorebot poll HTTP 502"))
    assert not _is_http_error(RuntimeError("curl: (28) timed out"))


def test_poll_gap_empty_vs_event_vs_timeout():
    assert poll_gap(0.4, got_event=False) == POLL_EMPTY_GAP - 0.4
    assert poll_gap(0.4, got_event=True) == POLL_MIN_GAP - 0.4
    assert poll_gap(30.0, got_event=False, timed_out=True) == POLL_MIN_GAP
    assert poll_gap(25.0, got_event=False) == 0.0
