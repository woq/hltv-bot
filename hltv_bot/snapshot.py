from __future__ import annotations

from pathlib import Path

_JS_PATH = Path(__file__).with_name("extract.js")
EXTRACT_JS = _JS_PATH.read_text(encoding="utf-8").strip()


def snapshot_stats_fingerprint(snap: dict) -> str:
    """Roster / history / map score — not alive or log (those live on the log message)."""
    teams = snap.get("teams") or []
    kad = []
    for t in teams:
        for p in t.get("players") or []:
            kad.append(
                f"{p.get('nick')}:{p.get('kills')}/{p.get('assists')}/{p.get('deaths')}/{p.get('adr')}"
            )
    hist = snap.get("history") or []
    hist_s = ",".join(f"{x.get('n')}{x.get('winner')}" for x in hist[-8:])
    return "|".join(
        [
            str(snap.get("scoreText") or ""),
            str(snap.get("ctScore") or ""),
            str(snap.get("tScore") or ""),
            str(snap.get("roundText") or ""),
            hist_s,
            ",".join(kad),
        ]
    )


def snapshot_log_fingerprint(snap: dict) -> str:
    log_rows = snap.get("log") or []
    visible_log = []
    for item in log_rows[:15]:
        if not isinstance(item, dict):
            continue
        visible_log.append(
            f"{item.get('type')}:{item.get('killer')}:{item.get('victim')}:{item.get('assister')}:{item.get('text')}:{item.get('weapon')}:{1 if item.get('headshot') else 0}"
        )
    log_s = ";".join(visible_log)
    teams = snap.get("teams") or []
    return "|".join(
        [
            str(snap.get("scoreText") or ""),
            str(snap.get("roundText") or ""),
            log_s,
            str(snap.get("transport") or ""),
            "b1" if snap.get("bombPlanted") else "b0",
            "f1" if snap.get("frozen") else "f0",
            str(snap.get("live")),
            ",".join(
                "1" if p.get("alive") else "0"
                for t in teams
                for p in (t.get("players") or [])
                if p.get("alive") is not None
            ),
        ]
    )


def snapshot_fingerprint(snap: dict) -> str:
    """Stable key so Telegram editMessageText only fires on real changes."""
    return snapshot_stats_fingerprint(snap) + "|" + snapshot_log_fingerprint(snap)
