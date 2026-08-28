from hltv_bot.eio import decode_payload, encode_event, parse_event, parse_open
from hltv_bot.scorebot import _is_timeout


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
