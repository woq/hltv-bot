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


@dataclass(frozen=True)
class RemindConfig:
    event_days: int = 7
    event_hours: int = 6
    min_stars: int = 1
    soon_minutes: int = SOON_MINUTES
    watch: bool = True
    event_watch: bool = True
    ignored: frozenset[str] = frozenset()
    followed: frozenset[str] = frozenset()
    covered: frozenset[str] = frozenset()
    digest_morning: int = 10
    digest_evening: int = 20


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
    """Default is stars plus a Major/T1 name.

    A followed match id, or an event id opened with /cover, is the extra set.
    """
    if _both_tbd(row):
        return False
    mid = str(row.get("id") or "")
    if mid and mid in cfg.followed:
        return True
    eid = str(row.get("event_id") or "")
    if eid and eid in cfg.covered:
        return True
    if _stars(row) < cfg.min_stars:
        return False
    return classify_tier(str(row.get("event") or "")) in {"Major", "T1"}


def _pair(score: str) -> tuple[int, int] | None:
    text = (score or "").strip()
    if "-" not in text:
        return None
    left, right = text.split("-", 1)
    if not left.isdigit() or not right.isdigit():
        return None
    return int(left), int(right)


def feed_sig(row: dict) -> str:
    parts = [score_text(row), (row.get("format") or "").strip().lower()]
    return "|".join(p for p in parts if p)


def score_text(row: dict) -> str:
    a = (row.get("score1") or "").strip()
    b = (row.get("score2") or "").strip()
    if not a and not b:
        return ""
    return f"{a or '0'}-{b or '0'}"


def _real_score(score: str) -> bool:
    pair = _pair(score)
    return pair is not None and pair != (0, 0)


def score_note(row: dict, *, scored: bool) -> str:
    """bo1 is the match. bo3/bo5 numbers on the list are the current map."""
    fmt = (row.get("format") or "").strip().lower()
    if fmt not in {"bo1", "bo3", "bo5"}:
        return ""
    if fmt == "bo1" or not scored:
        return fmt
    return f"当前图 · {fmt}"


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
    "preview": "预告",
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


def _match_caption(kind: str, row: dict, when: datetime | None, score: str = "") -> str:
    label = _KIND.get(kind, kind)
    t1 = h(row.get("team1") or "?")
    t2 = h(row.get("team2") or "?")
    show = score if kind in {"preview", "score", "final"} else ""
    pair = _score_pair(show)
    if pair:
        head = f"<b>{label}</b>  {t1} <code>{h(pair[0])}</code>–<code>{h(pair[1])}</code> {t2}"
    else:
        head = f"<b>{label}</b>  {t1} vs {t2}"
    lines = [head]
    event = (row.get("event") or "").strip()
    if event:
        lines.append(f"<i>{h(event)}</i>")
    note = score_note(row, scored=bool(pair))
    if note:
        lines.append(h(note))
    clock = _clock(when, str(row.get("time") or ""))
    if clock:
        lines.append(f"<code>{h(clock)}</code> UTC+8")
    link = _link(str(row.get("url") or ""))
    if link:
        lines.append(link)
    return "\n".join(lines)


def _match_card(kind: str, row: dict, when: datetime | None, score: str = "") -> dict:
    show = score if kind in {"preview", "score", "final"} else ""
    pair = _score_pair(show)
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
        "note": score_note(row, scored=bool(pair)),
        "clock": _clock(when, str(row.get("time") or "")),
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


def _zero_row(row: dict) -> dict:
    item = dict(row)
    item["score1"] = "0"
    item["score2"] = "0"
    return item


def _snapshot_match(row: dict, *, opened: bool, soon: bool, score: str, live: bool, previewed: bool) -> dict:
    return {
        "opened": opened,
        "soon": soon,
        "live": bool(live),
        "previewed": bool(previewed),
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
        "format": row.get("format") or "",
        "sig": feed_sig(row),
    }


def slate_start(now: datetime, morning_hour: int) -> datetime:
    """Match day opens at morning_hour UTC+8 and runs 24 hours, across midnight.

    A 02:00 China-time game belongs to the slate that opened at 10:00 the
    previous calendar day. That is the foreign evening, not a new day.
    """
    now = now.astimezone(CST)
    start = now.replace(hour=morning_hour, minute=0, second=0, microsecond=0)
    if now < start:
        start -= timedelta(days=1)
    return start


def digest_window(now: datetime, morning: int, evening: int) -> tuple[str, datetime, datetime] | None:
    """Which digest is due, and which start times it includes.

    Morning (10:00): the whole slate, through 10:00 next day.
    Evening (20:00): the rest of that slate, including after midnight.
    """
    if not (0 <= morning < evening <= 23):
        return None
    now = now.astimezone(CST)
    start = slate_start(now, morning)
    evening_at = start.replace(hour=evening)
    end = start + timedelta(days=1)
    if start <= now < evening_at:
        return f"{morning:02d}", start, end
    if evening_at <= now < end:
        return f"{evening:02d}", evening_at, end
    return None


def _in_window(row: dict, begin: datetime, end: datetime) -> bool:
    start = start_at(row)
    return start is not None and begin <= start < end


def _digest_rows(matches: list[dict], cfg: RemindConfig, begin: datetime, end: datetime) -> list[dict]:
    rows = []
    for row in matches:
        mid = str(row.get("id") or "")
        if not mid or mid in cfg.ignored or not match_allowed(row, cfg):
            continue
        if _in_window(row, begin, end):
            rows.append(row)
    rows.sort(key=lambda row: (start_at(row) or begin, str(row.get("event") or ""), str(row.get("id") or "")))
    return rows


def format_digest_html(rows: list[dict], *, hour: str, begin: datetime, end: datetime) -> str:
    lines = [f"<b>赛程</b>  <code>{h(hour)}:00</code>  UTC+8"]
    lines.append(
        f"<i>{begin.strftime('%m-%d %H:%M')} → {end.strftime('%m-%d %H:%M')}</i>"
    )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault((row.get("event") or "其它").strip() or "其它", []).append(row)
    shown = 0
    for event, items in grouped.items():
        eid = str(items[0].get("event_id") or "")
        head = f"<b>{h(event)}</b>"
        if eid:
            head += f"  <code>{h(eid)}</code>"
        lines.append(head)
        for row in items:
            if shown >= 24:
                break
            shown += 1
            when = start_at(row)
            clock = when.strftime("%m-%d %H:%M") if when else (row.get("time") or "")
            fmt = (row.get("format") or "").strip()
            face = f"{h(row.get('team1') or '?')} vs {h(row.get('team2') or '?')}"
            bits = [f"<code>{h(clock)}</code>", face]
            if fmt:
                bits.append(h(fmt))
            bits.append(f"<code>{h(row.get('id') or '')}</code>")
            lines.append("  ".join(bits))
        if shown >= 24:
            lines.append(f"还有 {len(rows) - 24} 场")
            break
    return "\n".join(lines)


def _digest_card(rows: list[dict], hour: str) -> dict:
    return {"view": "matches", "title": f"赛程  {hour}:00  ·  UTC+8", "rows": rows[:12]}


LIVE_POLL = 0.0
SOON_POLL = 120.0
QUIET_POLL = 6 * 3600.0
START_LEAD = 45 * 60
DIGEST_LEAD = 20 * 60


def choose_poll_wait(rows: list[dict], cfg: RemindConfig, now: datetime, digests: dict | None) -> float:
    """Seconds until the next matches-list fetch.

    0 means a match is live: the caller uses the 3–5s clock.
    Two minutes when a watched match is about to start, or a digest is due.
    Otherwise sleep until the next lead, and at most six hours.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=CST)
    else:
        now = now.astimezone(CST)
    if not cfg.watch and not cfg.event_watch:
        return QUIET_POLL
    watched = [
        row
        for row in rows
        if match_allowed(row, cfg) and str(row.get("id") or "") not in cfg.ignored
    ]
    if cfg.watch and any(row.get("live") == "1" for row in watched):
        return LIVE_POLL
    soon = False
    wakes: list[float] = [QUIET_POLL]
    if cfg.watch:
        for row in watched:
            if row.get("live") == "1":
                continue
            start = start_at(row)
            if start is None:
                continue
            delta = (start - now).total_seconds()
            if 0 <= delta <= START_LEAD:
                soon = True
            elif delta > START_LEAD:
                wakes.append(delta - START_LEAD)
    if cfg.event_watch:
        window = digest_window(now, cfg.digest_morning, cfg.digest_evening)
        sent_map = digests or {}
        if window is not None:
            hour, begin, _end = window
            done = {str(x) for x in (sent_map.get(begin.strftime("%Y-%m-%d")) or [])}
            if hour not in done:
                soon = True
        nxt = _upcoming_digest(now, cfg.digest_morning, cfg.digest_evening)
        if nxt is not None:
            lead = (nxt - now).total_seconds() - DIGEST_LEAD
            if lead > 0:
                wakes.append(lead)
    if soon:
        return SOON_POLL
    return max(60.0, min(wakes))


def _upcoming_digest(now: datetime, morning: int, evening: int) -> datetime | None:
    if not (0 <= morning < evening <= 23):
        return None
    start = slate_start(now, morning)
    evening_at = start.replace(hour=evening)
    nxt = start + timedelta(days=1)
    for at in (start, evening_at, nxt):
        if at > now:
            return at
    return nxt


def _apply_digest(
    base: dict,
    matches: list[dict],
    now: datetime,
    cfg: RemindConfig,
    notes: list[Notice],
    *,
    seed: bool,
) -> None:
    window = digest_window(now, cfg.digest_morning, cfg.digest_evening)
    if window is None:
        return
    hour, begin, end = window
    key = begin.strftime("%Y-%m-%d")
    sent = dict(base.get("digests") or {})
    done = {str(x) for x in (sent.get(key) or [])}
    if hour in done:
        return
    done.add(hour)
    sent[key] = sorted(done)
    # Keep a few slates so the file does not grow without bound.
    if len(sent) > 14:
        for old in sorted(sent)[:-14]:
            sent.pop(old, None)
    base["digests"] = sent
    if seed or not cfg.event_watch:
        return
    rows = _digest_rows(matches, cfg, begin, end)
    if not rows:
        return
    notes.append(
        Notice(
            f"d:{key}:{hour}",
            format_digest_html(rows, hour=hour, begin=begin, end=end),
            _digest_card(rows, hour),
        )
    )


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
                seeded[mid] = _snapshot_match(
                    row,
                    opened=False,
                    soon=live,
                    score=score_text(row),
                    live=live,
                    previewed=live,
                )
            base["matches"] = seeded
            base["matches_seeded"] = True
            _apply_digest(base, matches, now, cfg, notes, seed=True)
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
                known = mid in prev
                old = prev.get(mid) or {}
                live = row.get("live") == "1"
                score = score_text(row)
                old_score = str(old.get("score") or "")
                start = start_at(row)
                opened = bool(old.get("opened"))
                soon_sent = bool(old.get("soon")) or live
                previewed = bool(old.get("previewed"))
                speak = _speak(cfg, mid, base)
                became_live = known and live and "live" in old and not old.get("live")
                if became_live and not previewed:
                    if _real_score(score):
                        if speak:
                            notes.append(
                                Notice(
                                    f"m:{mid}:score:{feed_sig(row)}",
                                    _match_html("score", row, start, score),
                                    _match_card("score", row, start, score),
                                )
                            )
                        opened = True
                    else:
                        shown = _zero_row(row)
                        if speak:
                            notes.append(
                                Notice(
                                    f"m:{mid}:preview",
                                    _match_html("preview", shown, start, "0-0"),
                                    _match_card("preview", shown, start, "0-0"),
                                )
                            )
                        opened = True
                        score = "0-0"
                    previewed = True
                elif known and score != old_score and _real_score(score):
                    if speak:
                        notes.append(
                            Notice(
                                f"m:{mid}:score:{feed_sig(row)}",
                                _match_html("score", row, start, score),
                                _match_card("score", row, start, score),
                            )
                        )
                    opened = True
                if live:
                    soon_sent = True
                    previewed = True
                nxt[mid] = _snapshot_match(
                    row,
                    opened=opened,
                    soon=soon_sent,
                    score=score or str(old.get("score") or ""),
                    live=live,
                    previewed=previewed,
                )
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
                    "format": old.get("format"),
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
            _apply_digest(base, matches, now, cfg, notes, seed=False)

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
        base["events"] = stages
        base["events_seeded"] = True

    return base, notes
