from __future__ import annotations

from pathlib import Path

_JS_PATH = Path(__file__).with_name("extract.js")
EXTRACT_JS = _JS_PATH.read_text(encoding="utf-8").strip()


def snapshot_fingerprint(snap: dict) -> str:
    """Stable key so Telegram editMessageText only fires on real changes."""
    log0 = (snap.get("log") or [{}])[0]
    teams = snap.get("teams") or []
    kad = []
    for t in teams:
        for p in t.get("players") or []:
            kad.append(f"{p.get('nick')}:{p.get('kills')}/{p.get('deaths')}")
    hist = snap.get("history") or []
    hist_s = ",".join(f"{x.get('n')}{x.get('winner')}" for x in hist[-4:])
    return "|".join(
        [
            str(snap.get("scoreText") or ""),
            str(snap.get("roundText") or ""),
            str(log0.get("text") or ""),
            str(log0.get("type") or ""),
            hist_s,
            ",".join(kad),
        ]
    )
