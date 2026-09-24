"""Match start/score alerts and Tier1/Major event reminders. Times are UTC+8."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hltv_bot.events import classify_tier, country_code_to_emoji
from hltv_bot.format import h

CST = timezone(timedelta(hours=8))
SOON_MINUTES = 15


@dataclass(frozen=True)
class Notice:
    key: str
    html: str
    card: dict | None = None


STREAK_MARK = 5


@dataclass(frozen=True)
class RemindConfig:
    event_days: int = 7
    event_hours: int = 6
    min_stars: int = 1
    soon_minutes: int = SOON_MINUTES
    watch: bool = True
    ignored: frozenset[str] = frozenset()


def empty_state() -> dict:
    return {"matches_seeded": False, "events_seeded": False, "matches": {}, "events": {}}


def _both_tbd(row: dict) -> bool:
    a = (row.get("team1") or "").strip().upper()
    b = (row.get("team2") or "").strip().upper()
    return (not a or a in {"?", "TBD"}) and (not b or b in {"?", "TBD"})


def _stars(row: dict) -> int:
    try:
        return int(row.get("stars") or 0)
    except (TypeError, ValueError):
        return 0


def match_allowed(row: dict, cfg: RemindConfig) -> bool:
    """Stars meet the floor and the event name is Major or T1."""
    if _both_tbd(row) or _stars(row) < cfg.min_stars:
        return False
    return classify_tier(str(row.get("event") or "")) in {"Major", "T1"}


def _streak_n(row: dict) -> int:
    try:
        return int(row.get("streak") or 0)
    except (TypeError, ValueError):
        return 0


def _pair(score: str) -> tuple[int, int] | None:
    text = (score or "").strip()
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    if not left.isdigit() or not right.isdigit():
        return None
    return int(left), int(right)


def advance_streak(old_score: str, new_score: str, old_n: int, old_team: str, team1: str, team2: str) -> tuple[int, str]:
    """Count a one-sided score increase as consecutive round wins.

    The matches list only shows the current numbers. A side that gains points
    while the other stays put has won those rounds in a row since the last poll.
    """
    prev = _pair(old_score)
    cur = _pair(new_score)
    if cur is None:
        return 0, ""
    if prev is None:
        return 0, ""
    if prev == cur:
        return old_n, old_team
    gained1, gained2 = cur[0] - prev[0], cur[1] - prev[1]
    if gained1 > 0 and gained2 == 0:
        team, gain = team1, gained1
    elif gained2 > 0 and gained1 == 0:
        team, gain = team2, gained2
    else:
        return 0, ""
    if not team:
        return 0, ""
    if team == old_team:
        return old_n + gain, team
    return gain, team


def feed_sig(row: dict) -> str:
    parts = [score_text(row)]
    mp = (row.get("map_score") or "").strip()
    if mp:
        parts.append(f"{row.get('map') or ''}:{mp}")
    n = _streak_n(row)
    if n >= STREAK_MARK:
        parts.append(f"streak:{n}:{row.get('streak_team') or ''}")
    return "|".join(p for p in parts if p)


def score_text(row: dict) -> str:
    a = (row.get("score1") or "").strip()
    b = (row.get("score2") or "").strip()
    if not a and not b:
        return ""
    return f"{a or '0'}-{b or '0'}"


def start_at(row: dict) -> datetime | None:
    raw = str(row.get("unix") or "").strip()
    if not raw.isdigit():
        return None
    n = int(raw)
    if n > 10_000_000_000:
        n //= 1000
    try:
        return datetime.fromtimestamp(n, CST)
    except (OverflowError, OSError, ValueError):
        return None


def _clock(dt: datetime | None, fallback: str = "") -> str:
    if dt is None:
        return fallback
    return dt.strftime("%m-%d %H:%M")


def _link(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    word = "打开赛事" if "/events/" in url else "打开比赛"
    return f'<a href="{h(url)}">{word}</a>'


_KIND = {
    "soon": "即将开赛",
    "live": "已开赛",
    "score": "比分",
    "final": "结束",
}


def _score_pair(score: str) -> tuple[str, str] | None:
    text = (score or "").strip()
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    left, right = left.strip(), right.strip()
    if not left and not right:
        return None
    return left or "0", right or "0"


def _face(row: dict, score: str) -> str:
    t1 = h(row.get("team1") or "?")
    t2 = h(row.get("team2") or "?")
    pair = _score_pair(score)
    if pair is None:
        return f"<b>{t1}</b>\nvs\n<b>{t2}</b>"
    return f"<b>{t1}</b>\n<code>{h(pair[0])}</code>  –  <code>{h(pair[1])}</code>\n<b>{t2}</b>"


def _meta_lines(row: dict, when: datetime | None) -> list[str]:
    lines: list[str] = []
    event = (row.get("event") or "").strip()
    if event:
        lines.append(f"<i>{h(event)}</i>")
    map_name = (row.get("map") or "").strip()
    map_score = (row.get("map_score") or "").strip()
    if map_name or map_score:
        bits = [h(map_name)] if map_name else []
        if map_score:
            bits.append(f"<code>{h(map_score)}</code>")
        lines.append("  ".join(bits))
    clock = _clock(when, str(row.get("time") or ""))
    if clock:
        lines.append(f"<code>{h(clock)}</code>  ·  UTC+8")
    else:
        lines.append("UTC+8")
    return lines


def _streak_line(row: dict) -> str:
    n = _streak_n(row)
    team = (row.get("streak_team") or "").strip()
    if n < STREAK_MARK or not team:
        return ""
    return f"⚡  <b>{h(team)}</b>  连赢 <b>{n}</b> 回合"


def _match_caption(kind: str, row: dict, when: datetime | None, score: str = "") -> str:
    label = _KIND.get(kind, kind)
    t1 = h(row.get("team1") or "?")
    t2 = h(row.get("team2") or "?")
    show = score if kind in {"live", "score", "final"} else ""
    pair = _score_pair(show)
    if pair:
        head = f"<b>{label}</b>  {t1} <code>{h(pair[0])}</code>–<code>{h(pair[1])}</code> {t2}"
    else:
        head = f"<b>{label}</b>  {t1} vs {t2}"
    lines = [head]
    event = (row.get("event") or "").strip()
    if event:
        lines.append(f"<i>{h(event)}</i>")
    clock = _clock(when, str(row.get("time") or ""))
    if clock:
        lines.append(f"<code>{h(clock)}</code> UTC+8")
    streak = _streak_line(row)
    if streak and kind in {"live", "score", "final"}:
        lines.append(streak)
    link = _link(str(row.get("url") or ""))
    if link:
        lines.append(link)
    return "\n".join(lines)


def _match_card(kind: str, row: dict, when: datetime | None, score: str = "") -> dict:
    show = score if kind in {"live", "score", "final"} else ""
    pair = _score_pair(show)
    streak = ""
    n = _streak_n(row)
    team = (row.get("streak_team") or "").strip()
    if n >= STREAK_MARK and team and kind in {"live", "score", "final"}:
        streak = f"{team}  连赢 {n} 回合"
    return {
        "view": "match",
        "kind": kind,
        "label": _KIND.get(kind, kind),
        "team1": row.get("team1") or "?",
        "team2": row.get("team2") or "?",
        "logo1": row.get("team1_logo") or "",
        "logo2": row.get("team2_logo") or "",
        "event_logo": row.get("event_logo") or "",
        "pair": pair,
        "event": row.get("event") or "",
        "map": "  ".join(x for x in (row.get("map") or "", row.get("map_score") or "") if x),
        "clock": _clock(when, str(row.get("time") or "")),
        "streak": streak,
    }


def _match_html(kind: str, row: dict, when: datetime | None, score: str = "") -> str:
    return _match_caption(kind, row, when, score)


def _hours_left(ev: dict, now: datetime) -> float | None:
    start_ts = int(ev.get("start_ts") or 0)
    if start_ts <= 0:
        return None
    start = datetime.fromtimestamp(start_ts, CST)
    return (start - now).total_seconds() / 3600.0


def event_stage(ev: dict, now: datetime, cfg: RemindConfig) -> str:
    if ev.get("live"):
        return ""
    if classify_tier(str(ev.get("name") or "")) not in {"Major", "T1"}:
        return ""
    hours = _hours_left(ev, now)
    if hours is None or hours <= 0:
        return ""
    window = cfg.event_days * 24
    if hours > window:
        return ""
    if hours <= cfg.event_hours:
        return "hours"
    if hours <= 24 and window > 24:
        return "day"
    return "days"


def _remain_text(hours: float) -> str:
    if hours >= 48:
        return f"还有 {int(hours // 24)} 天"
    if hours >= 1:
        return f"还有 {int(hours)} 小时"
    return f"还有 {max(1, int(hours * 60))} 分钟"


def _event_html(ev: dict, now: datetime, stage: str) -> str:
    hours = _hours_left(ev, now) or 0
    start_ts = int(ev.get("start_ts") or 0)
    clock = ""
    if start_ts:
        clock = datetime.fromtimestamp(start_ts, CST).strftime("%m-%d %H:%M")
    tier = classify_tier(str(ev.get("name") or ""))
    loc = (ev.get("location") or "").strip()
    flag = country_code_to_emoji(str(ev.get("country_code") or ""))
    place = " ".join(bit for bit in (flag, h(loc) if loc else "") if bit)
    tail = "<b>最后提醒</b>" if stage == "hours" else _remain_text(hours)
    lines = [f"<b>赛事</b>  {h(tier)}  <b>{h(ev.get('name') or '')}</b>"]
    if place:
        lines.append(place)
    if clock:
        lines.append(f"<code>{h(clock)}</code> UTC+8")
    lines.append(tail)
    link = _link(str(ev.get("url") or ""))
    if link:
        lines.append(link)
    return "\n".join(lines)


def _event_card(ev: dict, now: datetime, stage: str) -> dict:
    hours = _hours_left(ev, now) or 0
    start_ts = int(ev.get("start_ts") or 0)
    clock = ""
    if start_ts:
        clock = datetime.fromtimestamp(start_ts, CST).strftime("%m-%d %H:%M")
    return {
        "view": "event",
        "tier": classify_tier(str(ev.get("name") or "")),
        "id": str(ev.get("id") or ""),
        "name": ev.get("name") or "",
        "logo_url": ev.get("logo_url") or "",
        "flag": country_code_to_emoji(str(ev.get("country_code") or "")),
        "location": (ev.get("location") or "").strip(),
        "clock": clock,
        "remain": "最后提醒" if stage == "hours" else _remain_text(hours),
    }


def _snapshot_match(row: dict, *, opened: bool, soon: bool, score: str) -> dict:
    return {
        "opened": opened,
        "soon": soon,
        "score": score,
        "team1": row.get("team1") or "",
        "team2": row.get("team2") or "",
        "team1_logo": row.get("team1_logo") or "",
        "team2_logo": row.get("team2_logo") or "",
        "event_logo": row.get("event_logo") or "",
        "event": row.get("event") or "",
        "url": row.get("url") or "",
        "time": row.get("time") or "",
        "unix": row.get("unix") or "",
        "score1": row.get("score1") or "",
        "score2": row.get("score2") or "",
        "map": row.get("map") or "",
        "map_score": row.get("map_score") or "",
        "streak": _streak_n(row),
        "streak_team": row.get("streak_team") or "",
        "sig": feed_sig(row),
    }


def _speak(cfg: RemindConfig, mid: str, state: dict) -> bool:
    if not cfg.watch or mid in cfg.ignored:
        return False
    if state.get("quiet_all"):
        return False
    quiet = {str(x) for x in (state.get("quiet_ids") or [])}
    return mid not in quiet


def plan_reminders(
    state: dict | None,
    matches: list[dict] | None,
    events: list[dict] | None,
    *,
    now: datetime,
    cfg: RemindConfig | None = None,
) -> tuple[dict, list[Notice]]:
    """Return the next state and notices. The first successful poll only seeds."""
    cfg = cfg or RemindConfig()
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    else:
        now = now.astimezone(CST)
    base = empty_state()
    if state:
        base.update(copy.deepcopy(state))
        base["matches"] = dict(base.get("matches") or {})
        base["events"] = dict(base.get("events") or {})
    notes: list[Notice] = []

    if matches is not None:
        if not base.get("matches_seeded"):
            seeded: dict = {}
            for row in matches:
                if not match_allowed(row, cfg):
                    continue
                mid = str(row.get("id") or "")
                if not mid:
                    continue
                live = row.get("live") == "1"
                started = row.get("started") == "1"
                start = start_at(row)
                soon = (
                    not live
                    and not started
                    and start is not None
                    and 0 < (start - now).total_seconds() <= cfg.soon_minutes * 60
                )
                seeded[mid] = _snapshot_match(
                    row,
                    opened=started,
                    soon=soon or live or started,
                    score=score_text(row),
                )
            base["matches"] = seeded
            base["matches_seeded"] = True
        else:
            prev = dict(base.get("matches") or {})
            nxt: dict = {}
            seen: set[str] = set()
            quiet = {str(x) for x in (base.get("quiet_ids") or [])}
            for row in matches:
                if not match_allowed(row, cfg):
                    continue
                mid = str(row.get("id") or "")
                if not mid:
                    continue
                seen.add(mid)
                old = prev.get(mid) or {}
                live = row.get("live") == "1"
                started = row.get("started") == "1"
                score = score_text(row)
                tracked = (row.get("map_score") or "").strip() or score
                old_tracked = (str(old.get("map_score") or "")).strip() or str(old.get("score") or "")
                if tracked == old_tracked:
                    row["streak"] = old.get("streak") or 0
                    row["streak_team"] = old.get("streak_team") or ""
                else:
                    n, team = advance_streak(
                        old_tracked,
                        tracked,
                        int(old.get("streak") or 0),
                        str(old.get("streak_team") or ""),
                        str(row.get("team1") or ""),
                        str(row.get("team2") or ""),
                    )
                    row["streak"] = n
                    row["streak_team"] = team
                sig = feed_sig(row)
                start = start_at(row)
                soon = (
                    not live
                    and not started
                    and start is not None
                    and 0 < (start - now).total_seconds() <= cfg.soon_minutes * 60
                )
                opened = bool(old.get("opened"))
                soon_sent = bool(old.get("soon"))
                old_sig = str(old.get("sig") or "")
                speak = _speak(cfg, mid, base)
                if started and not opened:
                    if speak:
                        notes.append(Notice(f"m:{mid}:live", _match_html("live", row, start, score), _match_card("live", row, start, score)))
                    opened = True
                    soon_sent = True
                elif soon and not soon_sent and not opened:
                    if speak:
                        notes.append(Notice(f"m:{mid}:soon", _match_html("soon", row, start), _match_card("soon", row, start)))
                    soon_sent = True
                elif opened and sig and sig != old_sig:
                    if speak:
                        notes.append(Notice(f"m:{mid}:score:{sig}", _match_html("score", row, start, score), _match_card("score", row, start, score)))
                if live or started:
                    soon_sent = True
                nxt[mid] = _snapshot_match(row, opened=opened, soon=soon_sent, score=score or str(old.get("score") or ""))
                quiet.discard(mid)
            for mid, old in prev.items():
                if mid in seen or not old.get("opened"):
                    continue
                row = {
                    "team1": old.get("team1"),
                    "team2": old.get("team2"),
                    "team1_logo": old.get("team1_logo"),
                    "team2_logo": old.get("team2_logo"),
                    "event_logo": old.get("event_logo"),
                    "event": old.get("event"),
                    "url": old.get("url"),
                    "time": old.get("time"),
                    "unix": old.get("unix"),
                    "score1": old.get("score1"),
                    "score2": old.get("score2"),
                    "map": old.get("map"),
                    "map_score": old.get("map_score"),
                    "streak": old.get("streak"),
                    "streak_team": old.get("streak_team"),
                }
                if _speak(cfg, mid, base):
                    notes.append(
                        Notice(
                            f"m:{mid}:final",
                            _match_html("final", row, start_at(row), str(old.get("score") or "")),
                            _match_card("final", row, start_at(row), str(old.get("score") or "")),
                        )
                    )
                quiet.discard(mid)
            base["matches"] = nxt
            base["quiet_ids"] = sorted(quiet)
            base["quiet_all"] = False

    if events is not None:
        stages: dict[str, str] = {}
        prev_ev = dict(base.get("events") or {})
        for ev in events:
            eid = str(ev.get("id") or "")
            if not eid:
                continue
            stage = event_stage(ev, now, cfg)
            if not stage:
                continue
            stages[eid] = stage
            if base.get("events_seeded") and prev_ev.get(eid) != stage:
                notes.append(Notice(f"e:{eid}:{stage}", _event_html(ev, now, stage), _event_card(ev, now, stage)))
        base["events"] = stages
        base["events_seeded"] = True

    return base, notes
