from hltv_bot.eio import encode_payload
from hltv_bot.scorebot import iter_poll_events, iter_scorebot
from hltv_bot.session import BrowserSession


class _Resp:
    def __init__(self, status, body, url="https://scorebot-lb.hltv.org/socket.io/"):
        self.status_code = status
        self.content = body
        self.cookies = None
        self.url = url


class _PollClient:
    def __init__(self, sess):
        self.sess = sess
        self.headers_seen = []
        self.n = 0

    def get(self, url, headers=None, timeout=None):
        self.headers_seen.append(dict(headers or {}))
        self.n += 1
        if self.n == 1:
            self.sess.cookie = "cf_clearance=tok; __cf_bm=after"
            return _Resp(200, encode_payload('42["log","{\\"log\\":[]}"]'), url)
        raise RuntimeError("stop poll")


def test_poll_get_sees_cookie_changed_between_calls():
    sess = BrowserSession("chrome131", {}, "cf_clearance=tok; __cf_bm=before")
    client = _PollClient(sess)
    out = []
    try:
        for ev in iter_poll_events(
            client,
            base="https://scorebot-lb.hltv.org",
            headers={"cookie": "cf_clearance=tok; __cf_bm=before"},
            sid="abc",
            list_id="1",
            timeout=1,
            sess=sess,
            skip_ready=True,
        ):
            out.append(ev)
    except RuntimeError as e:
        assert "stop poll" in str(e)
    assert len(client.headers_seen) >= 2
    assert "__cf_bm=before" in client.headers_seen[0].get("cookie", "")
    assert "__cf_bm=after" in client.headers_seen[1].get("cookie", "")


class _ReconnectSession:
    shared_gets: list

    def __init__(self, **kw):
        self.cookies = None

    def get(self, url, headers=None, timeout=None):
        _ReconnectSession.shared_gets.append(dict(headers or {}))
        if "sid=" in url:
            _ReconnectSession.sess.cookie = "cf_clearance=tok; __cf_bm=after"
            raise RuntimeError("drop poll")
        body = encode_payload(
            '0{"sid":"abc","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":60000}'
        )
        return _Resp(200, body, url)

    def post(self, url, data=None, headers=None, timeout=None):
        return _Resp(200, b"", url)

    def close(self):
        pass

    def ws_connect(self, *a, **k):
        raise RuntimeError("no ws")


def test_handshake_get_after_reconnect_sees_new_cookie(monkeypatch):
    sess = BrowserSession("chrome131", {"user-agent": "UA"}, "cf_clearance=tok; __cf_bm=before")
    _ReconnectSession.shared_gets = []
    _ReconnectSession.sess = sess
    monkeypatch.setattr("hltv_bot.scorebot.chrome_scorebot_enabled", lambda: False)
    monkeypatch.setattr("curl_cffi.requests.Session", _ReconnectSession)
    monkeypatch.setattr("hltv_bot.scorebot.reconnect_wait", lambda *a, **k: 0)
    monkeypatch.setattr("hltv_bot.scorebot.time.sleep", lambda *a, **k: None)
    n = 0
    try:
        for ev in iter_scorebot(sess, "1", timeout=1):
            n += 1
            if len(_ReconnectSession.shared_gets) >= 3:
                break
            if n > 20:
                break
    except RuntimeError:
        pass
    handshakes = [h for h in _ReconnectSession.shared_gets if "sid=" not in str(h)]
    # gets list stores headers only; handshake vs poll distinguished by call order.
    assert len(_ReconnectSession.shared_gets) >= 2
    first = _ReconnectSession.shared_gets[0].get("cookie", "")
    later = _ReconnectSession.shared_gets[-1].get("cookie", "")
    assert "__cf_bm=before" in first or "__cf_bm=after" in first
    assert "__cf_bm=after" in later
