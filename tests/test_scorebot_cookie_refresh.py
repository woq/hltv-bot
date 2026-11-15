from hltv_bot.eio import encode_payload
from hltv_bot.scorebot import iter_scorebot
from hltv_bot.session import BrowserSession


class _Resp:
    def __init__(self, status, body, url="https://scorebot-lb.hltv.org/socket.io/"):
        self.status_code = status
        self.content = body
        self.cookies = None
        self.url = url


def test_handshake_sees_cookie_updated_on_retry(monkeypatch):
    sess = BrowserSession("chrome131", {}, "cf_clearance=tok; __cf_bm=before")
    headers_seen = []
    n = 0

    class _Client:
        def __init__(self, *a, **k):
            self.cookies = None

        def get(self, url, headers=None, timeout=None):
            nonlocal n
            headers_seen.append(dict(headers or {}))
            n += 1
            if n == 1:
                sess.cookie = "cf_clearance=tok; __cf_bm=after"
                raise TimeoutError("retry handshake")
            body = encode_payload(
                '0{"sid":"abc","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":60000}'
            )
            return _Resp(200, body, url)

        def ws_connect(self, *a, **k):
            raise RuntimeError("stop after ws_connect")

        def close(self):
            pass

    monkeypatch.setattr("hltv_bot.scorebot.chrome_scorebot_enabled", lambda: False)
    monkeypatch.setattr("curl_cffi.requests.Session", _Client)
    monkeypatch.setattr("hltv_bot.scorebot.reconnect_wait", lambda *a, **k: 0)
    monkeypatch.setattr("hltv_bot.scorebot.time.sleep", lambda *a, **k: None)

    try:
        for ev in iter_scorebot(sess, "1", timeout=1):
            if ev[0] == "ws_fail":
                break
    except RuntimeError as e:
        assert "stop after ws_connect" in str(e)

    assert len(headers_seen) >= 2
    assert "__cf_bm=before" in headers_seen[0].get("cookie", "")
    assert "__cf_bm=after" in headers_seen[1].get("cookie", "")


class _ReconnectSession:
    shared_gets: list

    def __init__(self, **kw):
        self.cookies = None

    def get(self, url, headers=None, timeout=None):
        _ReconnectSession.shared_gets.append(dict(headers or {}))
        body = encode_payload(
            '0{"sid":"abc","upgrades":["websocket"],"pingInterval":25000,"pingTimeout":60000}'
        )
        return _Resp(200, body, url)

    def close(self):
        pass

    def ws_connect(self, *a, **k):
        _ReconnectSession.sess.cookie = "cf_clearance=tok; __cf_bm=after"
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
