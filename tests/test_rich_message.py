from hltv_bot.format import format_connecting_html, format_rich_html, plain_to_rich
from hltv_bot.telegram_api import Telegram


def test_plain_to_rich_wraps_newlines():
    html = plain_to_rich("第一行\n第二行\n\n下一段")
    assert "<p>第一行<br>第二行</p>" in html
    assert "<p>下一段</p>" in html


def test_plain_to_rich_keeps_block_html():
    src = "<h3>x</h3><p>y</p>"
    assert plain_to_rich(src) == src


def test_plain_send_message_uses_sendmessage_api():
    captured: list[tuple[str, dict]] = []
    tg = Telegram("token")

    def fake_call(method, payload):
        captured.append((method, payload))
        return {"message_id": 9}

    tg._call = fake_call  # type: ignore[method-assign]
    tg.send_message(1, "hello <code>/watch 1</code>")
    assert captured[0][0] == "sendMessage"
    assert captured[0][1]["parse_mode"] == "HTML"
    assert "rich_message" not in captured[0][1]


def test_watch_path_uses_rich_api():
    captured: list[tuple[str, dict]] = []
    tg = Telegram("token")

    def fake_call(method, payload):
        captured.append((method, payload))
        return {"message_id": 9}

    tg._call = fake_call  # type: ignore[method-assign]
    tg.send_rich(1, "<table bordered compact></table>")
    tg.edit_rich(1, 9, "<table bordered compact></table>")
    assert captured[0][0] == "sendRichMessage"
    assert captured[1][0] == "editMessageText"
    assert "html" in captured[0][1]["rich_message"]
    assert "html" in captured[1][1]["rich_message"]


def test_scoreboard_is_hltv_widget_tables():
    from test_format import SNAP

    rich = format_rich_html(SNAP)
    assert rich.count("<table") >= 2
    assert "<mark>CT</mark>" in rich
    assert "<b>T</b>" in rich
    assert "<aside>" not in rich
    assert "<h3>" not in rich
    assert "<ul>" not in rich
    assert "<mark>" in format_rich_html({**SNAP, "link": "disconnected"})
    assert "<caption>" in rich
    assert "compact" in rich


def test_connecting_has_no_fake_scoreboard():
    html = format_connecting_html(team1="G2", team2="Spirit", list_id="2396932")
    assert "G2" in html and "Spirit" in html
    assert "连接中" in html
    assert "0-0" not in html
    assert "<h3>" not in html
