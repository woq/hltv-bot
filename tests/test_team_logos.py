import time
from pathlib import Path

from hltv_bot import team_logos


def test_logo_cache_key_ignores_query():
    a = team_logos.logo_cache_key("https://img-cdn.hltv.org/teamlogo/g2.svg?w=50")
    b = team_logos.logo_cache_key("https://img-cdn.hltv.org/teamlogo/g2.svg?w=100")
    assert a == b
    assert a != team_logos.logo_cache_key("https://img-cdn.hltv.org/teamlogo/navi.svg")


def test_ensure_caches_and_prune_drops_stale(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(team_logos, "CACHE_DIR", tmp_path)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    monkeypatch.setattr(team_logos, "_download_many", lambda urls: {urls[0]: png})

    url = "https://img-cdn.hltv.org/teamlogo/g2.svg"
    team_logos.ensure_team_logos([url, url])
    path = tmp_path / f"{team_logos.logo_cache_key(url)}.png"
    assert path.is_file()
    uri = team_logos.cached_data_uri(url)
    assert uri.startswith("data:image/png;base64,")

    stale = tmp_path / "old.png"
    stale.write_bytes(png)
    old = time.time() - team_logos.MAX_AGE_SEC - 10
    import os

    os.utime(stale, (old, old))
    assert team_logos.prune_team_logos() == 1
    assert not stale.exists()
    assert path.is_file()


def test_team_event_and_flag_retention(monkeypatch, tmp_path: Path):
    from hltv_bot import events as events_mod

    team_dir = tmp_path / "teams"
    event_dir = tmp_path / "events"
    flag_dir = tmp_path / "flags"
    team_dir.mkdir()
    event_dir.mkdir()
    flag_dir.mkdir()
    monkeypatch.setattr(team_logos, "CACHE_DIR", team_dir)
    monkeypatch.setattr(events_mod, "_LOGO_CACHE_DIR", event_dir)
    monkeypatch.setattr(events_mod, "_FLAGS_CACHE_DIR", flag_dir)
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    team = team_dir / "team.png"
    event = event_dir / "8057.png"
    flag = flag_dir / "PL.gif"
    for path in (team, event, flag):
        path.write_bytes(png if path.suffix == ".png" else b"GIF89a" + b"\x00" * 48)
    eight_days = time.time() - 8 * 24 * 3600
    import os

    for path in (team, event, flag):
        os.utime(path, (eight_days, eight_days))

    assert team_logos.prune_team_logos() == 0
    events_mod.ensure_event_logos([])
    events_mod.ensure_flags([])
    assert team.is_file()
    assert not event.exists()
    assert flag.is_file()


def test_html_body_falls_through_to_chrome(monkeypatch):
    html = b"<html><body>nope</body></html>" + b"x" * 40
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    monkeypatch.setattr(team_logos, "_urllib_get", lambda url, timeout=8.0: html)
    seen: list[str] = []

    def chrome(urls, timeout=20.0):
        seen.extend(urls)
        return {
            "https://img-cdn.hltv.org/teamlogo/a.svg": png,
            "https://img-cdn.hltv.org/teamlogo/b.svg": html,
        }

    monkeypatch.setattr(team_logos, "_chrome_batch", chrome)
    out = team_logos.download_images(
        ["https://img-cdn.hltv.org/teamlogo/a.svg", "https://img-cdn.hltv.org/teamlogo/b.svg"]
    )
    assert set(seen) == {
        "https://img-cdn.hltv.org/teamlogo/a.svg",
        "https://img-cdn.hltv.org/teamlogo/b.svg",
    }
    assert out["https://img-cdn.hltv.org/teamlogo/a.svg"].startswith(b"\x89PNG")
    assert "https://img-cdn.hltv.org/teamlogo/b.svg" not in out


def test_download_images_keeps_every_url(monkeypatch):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    monkeypatch.setattr(team_logos, "_urllib_get", lambda url, timeout=8.0: png)
    monkeypatch.setattr(team_logos, "_chrome_batch", lambda urls, timeout=20.0: {})
    urls = [f"https://img-cdn.hltv.org/teamlogo/{i}.png" for i in range(45)]
    out = team_logos.download_images(urls)
    assert set(out) == set(urls)


def test_sniff_rejects_html():
    assert team_logos._sniff(b"<html><body>nope</body></html>" + b"x" * 40) is None
    assert team_logos._sniff(b"<?xml version='1.0'?><svg xmlns='http://www.w3.org/2000/svg'></svg>") == "svg"
