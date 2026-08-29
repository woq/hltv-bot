from pathlib import Path

from hltv_bot.format import format_connecting_html, format_rich_html, plain_to_rich
from hltv_bot.telegram_api import Telegram

ROOT = Path(__file__).resolve().parents[1] / "hltv_bot"


def test_plain_to_rich_wraps_newlines():
    html = plain_to_rich("第一行\n第二行\n\n下一段")
    assert "<p>第一行<br>第二行</p>" in html
    assert "<p>下一段</p>" in html


def test_plain_to_rich_keeps_block_html():
    src = "<h3>x</h3><p>y</p>"
    assert plain_to_rich(src) == src


def test_telegram_send_and_edit_use_rich_api():
    captured: list[tuple[str, dict]] = []
    tg = Telegram("token")

    def fake_call(method, payload):
        captured.append((method, payload))
        return {"message_id": 9}

    tg._call = fake_call  # type: ignore[method-assign]
    tg.send_message(1, "hello")
    tg.edit_message(1, 9, "hello")
    assert captured[0][0] == "sendRichMessage"
    assert captured[1][0] == "editMessageText"
    for _, payload in captured:
        assert "text" not in payload
        assert "parse_mode" not in payload
        assert payload["rich_message"]["html"].startswith("<p>")


def test_source_never_calls_sendmessage_api():
    hits = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if "sendMessage" in line and "sendRichMessage" not in line:
                hits.append(f"{path.relative_to(ROOT.parent)}:{i}:{line.strip()}")
    assert hits == []


def test_scoreboard_is_two_team_tables():
    from test_format import SNAP

    rich = format_rich_html(SNAP)
    assert rich.count("<table") == 2
    assert "CT · Spirit" in rich
    assert "T · G2" in rich
    assert "<mark>" in format_rich_html({**SNAP, "link": "disconnected"})
    assert "<caption>" in rich
    assert "compact" in rich


def test_connecting_has_no_fake_scoreboard():
    html = format_connecting_html(team1="G2", team2="Spirit", list_id="2396932")
    assert "<table" not in html
    assert "G2" in html and "Spirit" in html
    assert "connecting" in html
    assert "0-0" not in html
