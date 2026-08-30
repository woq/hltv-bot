from hltv_bot.eio import (
    Yeast,
    classify_eio,
    decode_payload,
    encode_event,
    parse_event,
    parse_open,
    split_ws_packets,
    yeast_encode,
)
from hltv_bot.scorebot import (
    WS_RETRY_EVERY,
    POLL_5XX_GAP,
    POLL_EMPTY_GAP,
    POLL_MIN_GAP,
    RECONNECT_5XX,
    RECONNECT_MAX,
    RECONNECT_MIN,
    _http_status_from_exc,
    _is_http_error,
    _is_timeout,
    _poll_url,
    _ws_headers,
    _ws_url,
    cookie_header,
    http_to_ws,
    is_poll_5xx,
    iter_ws_events,
    merged_ws_cookies,
    next_backoff,
    ws_upgrade_refused,
    poll_gap,
    probe_upgrade,
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
    assert not _is_http_error(RuntimeError("scorebot poll HTTP 400"))
    assert is_poll_5xx(502)
    assert is_poll_5xx(524)
    assert not is_poll_5xx(400)
    assert not is_poll_5xx(403)


def test_poll_gap_empty_vs_event_vs_timeout():
    assert POLL_MIN_GAP >= 5.0
    assert POLL_EMPTY_GAP >= 20.0
    assert poll_gap(0.4, got_event=False) == POLL_EMPTY_GAP - 0.4
    assert poll_gap(0.4, got_event=True) == POLL_MIN_GAP - 0.4
    assert poll_gap(30.0, got_event=False, timed_out=True) == POLL_MIN_GAP
    assert poll_gap(25.0, got_event=False) == 0.0
    assert poll_gap(0.4, got_event=False, http_5xx=True) == POLL_5XX_GAP


def test_merged_ws_cookies_keep_io_over_header():
    jar = {"io": "sid-from-jar", "cf_clearance": "x"}
    out = merged_ws_cookies("cf_clearance=old; foo=1", jar)
    assert out["io"] == "sid-from-jar"
    assert out["cf_clearance"] == "x"
    assert out["foo"] == "1"
    from_hdr = merged_ws_cookies("", "cf_clearance=abc; foo=1", {"io": "sid"})
    assert from_hdr["cf_clearance"] == "abc"
    assert from_hdr["io"] == "sid"


def test_ws_retry_interval_is_bounded():
    assert 15.0 <= WS_RETRY_EVERY <= 60.0


def test_ws_upgrade_refused():
    assert ws_upgrade_refused(
        RuntimeError("Failed to perform, curl: (22) Refused WebSocket upgrade: 403")
    )
    assert not ws_upgrade_refused(RuntimeError("scorebot poll HTTP 502"))


def test_yeast_t_matches_engine_io_client():
    assert yeast_encode(0) == "0"
    clock = Yeast()
    a = clock.next(1_788_092_239_000)
    assert a and not a.isdigit()
    assert all(ch.isalnum() or ch in "-_" for ch in a)
    b = clock.next(1_788_092_239_000)
    assert b == a + ".0"
    c = clock.next(1_788_092_239_000)
    assert c == a + ".1"
    d = clock.next(1_788_092_239_001)
    assert d != a and "." not in d
    assert "t=" in _poll_url("https://scorebot-lb.hltv.org")
    ws = _ws_url("https://scorebot-lb.hltv.org", {"sid": "abc"})
    assert "transport=websocket" in ws
    t = [p.split("=", 1)[1] for p in ws.split("?")[1].split("&") if p.startswith("t=")][0]
    assert t and not t.isdigit()


def test_cookie_header_puts_cf_names_first():
    raw = cookie_header(
        {
            "foo": "1",
            "cf_clearance": "c",
            "io": "sid",
            "__cf_bm": "b",
            "_cfuvid": "u",
        }
    )
    names = [p.split("=", 1)[0] for p in raw.split("; ")]
    assert names[:4] == ["io", "_cfuvid", "cf_clearance", "__cf_bm"]
    assert names[-1] == "foo"


def test_ws_headers_drop_cookie_and_priority():
    h = _ws_headers(
        {
            "user-agent": "UA",
            "origin": "https://www.hltv.org",
            "cookie": "secret=1",
            "priority": "u=1, i",
            "accept": "*/*",
            "accept-encoding": "gzip, deflate, br, zstd",
        }
    )
    keys = {k.lower() for k in h}
    assert "cookie" not in keys
    assert "priority" not in keys
    assert "accept" not in keys
    assert "accept-encoding" not in keys
    assert "sec-websocket-extensions" not in keys
    assert h["sec-fetch-mode"] == "websocket"
    assert h["origin"] == "https://www.hltv.org"


def test_ws_upgrade_403_is_http_status():
    err = RuntimeError("Failed to perform, curl: (22) Refused WebSocket upgrade: 403")
    assert _http_status_from_exc(err) == 403


def test_ws_url_uses_wss_and_sid():
    assert http_to_ws("https://scorebot-lb.hltv.org") == "wss://scorebot-lb.hltv.org"
    url = _ws_url("https://scorebot-lb.hltv.org", {"sid": "abc"})
    assert url.startswith("wss://scorebot-lb.hltv.org/socket.io/?")
    assert "transport=websocket" in url
    assert "sid=abc" in url
    assert "EIO=3" in url


def test_classify_eio_packets():
    assert classify_eio("2") == ("ping", "2")
    assert classify_eio("2probe")[0] == "ping"
    assert classify_eio("3probe")[0] == "pong"
    kind, payload = classify_eio('42["log",{"log":[]}]')
    assert kind == "event"
    assert payload[0] == "log"
    assert classify_eio("1")[0] == "close"


def test_split_ws_v4_separator():
    assert split_ws_packets("2\x1e3") == ["2", "3"]


class _FakeWS:
    def __init__(self, incoming: list[str]):
        self.incoming = list(incoming)
        self.sent: list[str] = []

    def send_str(self, s: str) -> None:
        self.sent.append(s)

    def recv_str(self) -> str:
        if not self.incoming:
            raise TimeoutError("timed out")
        return self.incoming.pop(0)


def test_probe_upgrade_sends_2probe_then_5():
    ws = _FakeWS(["3probe"])
    extra = probe_upgrade(ws)
    assert extra == []
    assert ws.sent == ["2probe", "5"]


def test_probe_upgrade_keeps_early_events():
    pkt = '42["scoreboard",{"mapName":"de_dust2"}]'
    ws = _FakeWS([pkt, "3probe"])
    extra = probe_upgrade(ws)
    assert extra == [pkt]
    assert ws.sent[-1] == "5"


def test_iter_ws_events_pong_and_log():
    log_pkt = '42["log","{\\"log\\":[{\\"Kill\\":{\\"killerNick\\":\\"donk\\"}}]}"]'
    ws = _FakeWS([log_pkt, "2"])
    out = []
    try:
        for ev in iter_ws_events(ws):
            out.append(ev)
            if len(out) >= 4:
                break
    except TimeoutError:
        pass
    names = [n for n, _ in out]
    assert "log" in names
    assert "tick" in names
    assert ws.sent == ["3"]
    log_ev = next(p for n, p in out if n == "log")
    assert log_ev["log"][0]["Kill"]["killerNick"] == "donk"


def test_ready_event_is_not_xhr_framed():
    s = encode_event("readyForMatch", '{"token":"","listId":"1"}')
    assert s.startswith("42[")
    assert not s.startswith("\x00")


class _StopPoll:
    def get(self, url, headers=None, timeout=None):
        raise RuntimeError("stop poll")


def test_iter_poll_events_emits_ws_fail():
    from hltv_bot.scorebot import iter_poll_events

    out = []
    try:
        for ev in iter_poll_events(
            _StopPoll(),
            base="https://scorebot-lb.hltv.org",
            headers={},
            sid="abc",
            list_id="1",
            timeout=1,
            skip_ready=True,
            ws_factory=lambda: (None, [], RuntimeError("Refused WebSocket upgrade: 403")),
            ws_retry_every=999,
        ):
            out.append(ev)
    except RuntimeError as e:
        assert "stop poll" in str(e)
    fail = next(p for n, p in out if n == "ws_fail")
    assert fail["n"] == 1
    assert "403" in fail["error"]
