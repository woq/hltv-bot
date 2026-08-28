from hltv_bot.settings import parse_real_arg, set_real, is_real
from hltv_bot.fixtures import MOCK_MATCHES
from hltv_bot.format import format_match_list


def test_parse_real_arg():
    assert parse_real_arg("") is False
    assert parse_real_arg("1") is True
    assert parse_real_arg("on") is True
    assert parse_real_arg("0") is False
    assert parse_real_arg("nope") is None


def test_set_real_persists(tmp_path):
    p = tmp_path / "settings.json"
    assert is_real(p) is False
    assert set_real(True, p) is True
    assert is_real(p) is True
    assert set_real(False, p) is False


def test_mock_matches_format():
    text = format_match_list(MOCK_MATCHES, starred_only=True)
    assert "G2" in text
    assert "2397226" not in text
    all_text = format_match_list(MOCK_MATCHES, starred_only=False)
    assert "2397226" in all_text
