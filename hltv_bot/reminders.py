"""Match start/score alerts and Tier1/Major event reminders. Times are UTC+8."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from hltv_bot.events import classify_tier, country_code_to_emoji, remain_text, tier_label
from hltv_bot.format import h

CST = timezone(timedelta(hours=8))
SOON_MINUTES = 15


@dataclass(frozen=True)
class Notice:
    key: str
    html: str
    card: dict | None = None
    match_id: str = ""
    lane: str = ""
    admins_only: bool = False
    row: dict | None = None


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
    score_multi: frozenset[str] = frozenset()
    score_single: frozenset[str] = frozenset()
    digest_morning: int = 10
    digest_evening: int = 20


def empty_state() -> dict:
    return {"matches_seeded": False, "events_seeded": False, "matches": {}, "events": {}}


def _both_tbd(row: dict) -> bool:
    from hltv_bot.matches import both_sides_open

    return both_sides_open(row)


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
    stars = _stars(row)
    if stars < cfg.min_stars:
        return False
    return classify_tier(str(row.get("event") or ""), stars=stars) in {"Major", "T1"}


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


def _multi_match(row: dict, cfg: RemindConfig) -> bool:
    """Default stars plus Major/T1, or an event opened with /cover."""
    eid = str(row.get("event_id") or "")
    if eid and eid in cfg.covered:
        return True
    stars = _stars(row)
    if stars < cfg.min_stars:
        return False
    return classify_tier(str(row.get("event") or ""), stars=stars) in {"Major", "T1"}


def score_lane(row: dict, cfg: RemindConfig) -> str:
    """single is /follow. multi is the default list and /cover."""
    mid = str(row.get("id") or "")
    single = bool(mid and mid in cfg.followed)
    multi = _multi_match(row, cfg)
    if single and multi:
        return "both"
    if single:
        return "single"
    if multi:
        return "multi"
    return ""


def lane_open(row: dict, cfg: RemindConfig) -> bool:
    """Empty per-chat sets keep the old engine tests. A set means only those chats."""
    if not cfg.score_multi and not cfg.score_single:
        return bool(cfg.watch)
    lane = score_lane(row, cfg)
    if lane == "both":
        return bool(cfg.score_multi or cfg.score_single)
    if lane == "multi":
        return bool(cfg.score_multi)
    if lane == "single":
        return bool(cfg.score_single)
    return False


def _won_pair(row: dict) -> tuple[int, int] | None:
    left, right = str(row.get("won1") or ""), str(row.get("won2") or "")
    if left.isdigit() and right.isdigit():
        return int(left), int(right)
    return None


def _forward_pair(old: tuple[int, int] | None, new: tuple[int, int] | None) -> tuple[int, int] | None:
    """Keep the previous pair when either side of the new reading is lower."""
    if new is None:
        return old
    if old is None:
        return new
    if new[0] >= old[0] and new[1] >= old[1]:
        return new
    return old


def _parse_round_list(raw: str) -> list[tuple[int, int] | None]:
    items: list[tuple[int, int] | None] = []
    for part in str(raw or "").split(","):
        text = part.strip()
        items.append(_pair(text) if text else None)
    return items


def _format_round_list(items: list[tuple[int, int] | None]) -> str:
    return ",".join("" if item is None else f"{item[0]}-{item[1]}" for item in items)


def _stored_rounds(old: dict) -> list[tuple[int, int] | None]:
    if "map_rounds" in old:
        return _parse_round_list(str(old.get("map_rounds") or ""))
    pair = _pair(str(old.get("score") or ""))
    if pair is None:
        return []
    raw = str(old.get("map_index") or "")
    idx = int(raw) if raw.isdigit() else 0
    items: list[tuple[int, int] | None] = [None] * (idx + 1)
    items[idx] = pair
    return items


def _map_slot(won: tuple[int, int], rounds: tuple[int, int] | None, n_maps: int) -> int:
    from hltv_bot.matches import map_is_over

    played = won[0] + won[1]
    finished = rounds is not None and map_is_over(*rounds)
    idx = played - 1 if finished and played > 0 else played
    if idx < 0:
        idx = 0
    if n_maps and idx >= n_maps:
        idx = n_maps - 1
    return idx


def _low_reset(previous: tuple[int, int] | None, incoming: tuple[int, int]) -> bool:
    from hltv_bot.matches import map_is_over

    if previous is None or not map_is_over(*previous):
        return False
    return max(incoming) <= 5 and (incoming[0] < previous[0] or incoming[1] < previous[1])


def cache_match_score(old: dict, row: dict) -> dict:
    """Remember series wins and each map's rounds. A later reading can only add.

    The matches list sometimes omits ``maps-won`` or repeats an older round
    score. A lower number stays on the shelf. A finished map followed by a
    single-digit score is the next map, not a rewrite of the one that ended.
    """
    from hltv_bot.matches import map_is_over

    view = dict(row)
    n_maps = len(_map_names(row) or _map_names(old))
    stored = _stored_rounds(old)
    old_won = _won_pair(old)
    row_won = _won_pair(row)
    won = _forward_pair(old_won, row_won)
    incoming = _pair(score_text(row))
    if incoming is not None:
        won_now = won if won is not None else (0, 0)
        grew = (
            old_won is not None
            and won is not None
            and won[0] >= old_won[0]
            and won[1] >= old_won[1]
            and (won[0] + won[1]) > (old_won[0] + old_won[1])
        )
        stale_series = (
            old_won is not None
            and row_won is not None
            and (row_won[0] < old_won[0] or row_won[1] < old_won[1])
            and max(incoming) > 5
        )
        if stale_series and row_won is not None:
            slot = _map_slot(row_won, incoming, n_maps)
        else:
            slot = _map_slot(won_now, incoming, n_maps)
            row_idx = str(row.get("map_index") or "")
            if (
                slot > 0
                and (slot >= len(stored) or stored[slot] is None)
                and stored[slot - 1] is not None
                and map_is_over(*stored[slot - 1])
                and max(incoming) > 5
                and incoming[0] <= stored[slot - 1][0]
                and incoming[1] <= stored[slot - 1][1]
                and (not row_idx.isdigit() or int(row_idx) < slot)
            ):
                slot = slot - 1
        while len(stored) <= slot:
            stored.append(None)
        if stored[slot] is not None and _low_reset(stored[slot], incoming) and not grew and not stale_series:
            previous = stored[slot]
            if previous is not None and previous[0] != previous[1] and (won_now[0] + won_now[1]) <= slot:
                bumped = [won_now[0], won_now[1]]
                bumped[0 if previous[0] > previous[1] else 1] += 1
                won = (bumped[0], bumped[1])
                won_now = won
            slot = _map_slot(won_now, incoming, n_maps)
            while len(stored) <= slot:
                stored.append(None)
        stored[slot] = _forward_pair(stored[slot], incoming)
        pair = stored[slot]
        if pair is not None and map_is_over(*pair) and pair[0] != pair[1]:
            base = won if won is not None else (0, 0)
            if base[0] + base[1] <= slot:
                side = 0 if pair[0] > pair[1] else 1
                won = (base[0] + int(side == 0), base[1] + int(side == 1))
    shown = next((i for i in range(len(stored) - 1, -1, -1) if stored[i] is not None), None)
    if shown is not None and stored[shown] is not None:
        left, right = stored[shown]
        view["score1"] = str(left)
        view["score2"] = str(right)
        view["map_index"] = str(shown)
    if won is not None:
        view["won1"] = str(won[0])
        view["won2"] = str(won[1])
    view["map_rounds"] = _format_round_list(stored)
    return view


def accept_round_score(old: dict, row: dict) -> bool:
    """On one map each side can only stay or go up.

    A new map is a series that gained a win without either side losing one,
    or a finished map resetting to a low score. A lower series tally is noise.
    """
    from hltv_bot.matches import map_is_over

    new = _pair(score_text(row))
    if new is None:
        return False
    old_score = _pair(str(old.get("score") or ""))
    if old_score is None:
        return True
    old_won = _won_pair(old)
    new_won = _won_pair(row)
    if (
        old_won is not None
        and new_won is not None
        and new_won[0] >= old_won[0]
        and new_won[1] >= old_won[1]
        and new_won != old_won
    ):
        return True
    old_idx = str(old.get("map_index") or "")
    new_idx = str(row.get("map_index") or "")
    if old_idx.isdigit() and new_idx.isdigit() and int(new_idx) > int(old_idx):
        return True
    if map_is_over(*old_score) and max(new) <= 5 and (new[0] < old_score[0] or new[1] < old_score[1]):
        return True
    return new[0] >= old_score[0] and new[1] >= old_score[1]


def _fmt(row: dict) -> str:
    return (row.get("format") or "").strip().lower()


def _map_names(row: dict) -> list[str]:
    import re

    return [part.strip() for part in re.split(r"\s*·\s*", row.get("maps") or "") if part.strip()]


def _parse_winners(raw: str, n: int) -> list[int]:
    wins: list[int] = []
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        wins.append(int(part) if part in {"0", "1", "2"} else 0)
    if n and len(wins) < n:
        wins.extend([0] * (n - len(wins)))
    return wins[:n] if n else wins


def _winners_text(wins: list[int]) -> str:
    return ",".join(str(item) for item in wins)


def _baseline_winners(old: dict, n: int) -> list[int]:
    if "map_winners" in old:
        return _parse_winners(str(old.get("map_winners") or ""), n)
    wins = [0] * n
    base = _won_pair(old)
    if base and n:
        if base[0] and not base[1]:
            for i in range(min(base[0], n)):
                wins[i] = 1
        elif base[1] and not base[0]:
            for i in range(min(base[1], n)):
                wins[i] = 2
    return wins


def merge_map_winners(old: dict, row: dict, rounds: tuple[int, int] | None) -> list[int]:
    """Remember who won each map. The list only has the series tally, not the order."""
    from hltv_bot.matches import map_is_over

    names = _map_names(row) or _map_names(old)
    n = len(names)
    wins = _baseline_winners(old, n)
    old_won = _won_pair(old) or (0, 0)
    new_won = _won_pair(row)
    if new_won is not None and n and not any(wins) and (new_won[0] == 0) != (new_won[1] == 0):
        old_won = (0, 0)
    if new_won is not None and n:
        d1, d2 = new_won[0] - old_won[0], new_won[1] - old_won[1]

        def place(side: int, count: int) -> None:
            left = count
            for i in range(n):
                if left <= 0:
                    return
                if wins[i] == 0:
                    wins[i] = side
                    left -= 1

        if d1 > 0 and d2 == 0:
            place(1, d1)
        elif d2 > 0 and d1 == 0:
            place(2, d2)
    if rounds and n and map_is_over(*rounds):
        idx_raw = str(row.get("map_index") or "")
        if idx_raw.isdigit():
            idx = int(idx_raw)
            if 0 <= idx < n and wins[idx] == 0 and rounds[0] != rounds[1]:
                wins[idx] = 1 if rounds[0] > rounds[1] else 2
    return wins


def _series_tally(row: dict, winners: list[int]) -> tuple[int, int]:
    won = _won_pair(row)
    counted = (sum(1 for item in winners if item == 1), sum(1 for item in winners if item == 2))
    if won is None:
        return counted
    if counted[0] + counted[1] > won[0] + won[1]:
        return counted
    return won


def _series_target(fmt: str) -> int:
    return {"bo1": 1, "bo3": 2, "bo5": 3}.get(fmt, 0)


def _clinched(row: dict, winners: list[int], rounds: tuple[int, int] | None) -> bool:
    from hltv_bot.matches import map_is_over

    fmt = _fmt(row)
    target = _series_target(fmt)
    if target <= 0:
        return False
    if fmt == "bo1":
        return rounds is not None and map_is_over(*rounds)
    return max(_series_tally(row, winners)) >= target


def _fresh_wins(old: dict, winners: list[int]) -> list[int]:
    prev = _baseline_winners(old, len(winners))
    found: list[int] = []
    for i, side in enumerate(winners):
        before = prev[i] if i < len(prev) else 0
        if before == 0 and side in {1, 2}:
            found.append(i)
    return found


def _map_rows(row: dict, winners: list[int], *, rounds: tuple[int, int] | None = None) -> list[dict]:
    names = _map_names(row)
    idx = str(row.get("map_index") or "")
    current = int(idx) if idx.isdigit() else -1
    round_list = _parse_round_list(str(row.get("map_rounds") or ""))
    rows: list[dict] = []
    for i, name in enumerate(names):
        side = winners[i] if i < len(winners) else 0
        team = team_id = logo = ""
        loser_team = loser_team_id = loser_logo = ""
        if side == 1:
            team, team_id, logo = row.get("team1") or "", row.get("team1_id") or "", row.get("team1_logo") or ""
            loser_team, loser_team_id, loser_logo = row.get("team2") or "", row.get("team2_id") or "", row.get("team2_logo") or ""
        elif side == 2:
            team, team_id, logo = row.get("team2") or "", row.get("team2_id") or "", row.get("team2_logo") or ""
            loser_team, loser_team_id, loser_logo = row.get("team1") or "", row.get("team1_id") or "", row.get("team1_logo") or ""

        map_score = ""
        pair = round_list[i] if i < len(round_list) and round_list[i] is not None else None
        if pair is None and (i == current or len(names) == 1) and rounds:
            pair = rounds
        if pair is None and side != 0:
            s1 = str(row.get("score1") or "")
            s2 = str(row.get("score2") or "")
            if s1.isdigit() and s2.isdigit() and (i == current or len(names) == 1):
                pair = (int(s1), int(s2))
        if pair and side != 0:
            map_score = f"{max(pair)}-{min(pair)}"

        rows.append(
            {
                "name": name,
                "winner": side,
                "current": i == current,
                "team": team,
                "team_id": team_id,
                "logo": logo,
                "loser_team": loser_team,
                "loser_team_id": loser_team_id,
                "loser_logo": loser_logo,
                "score": map_score,
            }
        )
    return rows


def _map_caption(rows: list[dict]) -> str:
    bits = []
    for item in rows:
        name = str(item.get("name") or "")
        team = str(item.get("team") or "")
        score = str(item.get("score") or "").strip()
        loser = str(item.get("loser_team") or "")
        if team and score and loser:
            bits.append(f"{name} {team} {score} {loser}".strip())
        elif team and score:
            bits.append(f"{name} {team} {score}".strip())
        elif team:
            bits.append(f"{name} {team}".strip())
        else:
            bits.append(name)
    return " · ".join(bit for bit in bits if bit)


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
    "halftime": "半场",
    "map": "Map winner",
    "match": "Match winner",
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


def _shown_pair(kind: str, row: dict, score: str, winners: list[int]) -> tuple[str, str] | None:
    if kind == "match" and _fmt(row) in {"bo3", "bo5"}:
        left, right = _series_tally(row, winners)
        if left or right:
            return str(left), str(right)
    return _score_pair(score if kind in {"preview", "score", "halftime", "map", "match"} else "")


def _map_score_line(kind: str, row: dict, rounds: tuple[int, int] | None) -> str:
    if kind != "match" or _fmt(row) not in {"bo3", "bo5"} or not rounds or rounds == (0, 0):
        return ""
    return f"本图 {rounds[0]}–{rounds[1]}"


def _match_card(
    kind: str,
    row: dict,
    when: datetime | None,
    score: str = "",
    *,
    winners: list[int] | None = None,
    winner: int = 0,
    rounds: tuple[int, int] | None = None,
) -> dict:
    wins = list(winners or [])
    pair = _shown_pair(kind, row, score, wins)
    rows = _map_rows(row, wins, rounds=rounds)
    return {
        "view": "match",
        "kind": kind,
        "label": _KIND.get(kind, kind),
        "team1": row.get("team1") or "?",
        "team2": row.get("team2") or "?",
        "logo1": row.get("team1_logo") or "",
        "logo2": row.get("team2_logo") or "",
        "team1_id": row.get("team1_id") or "",
        "team2_id": row.get("team2_id") or "",
        "event_id": row.get("event_id") or "",
        "event_logo": row.get("event_logo") or "",
        "pair": pair,
        "winner": winner if winner in {1, 2} else 0,
        "map_rows": rows,
        "map_score": _map_score_line(kind, row, rounds),
        "event": row.get("event") or "",
        "note": "",
        "clock": _clock(when, str(row.get("time") or "")),
    }


def _match_caption(card: dict, row: dict) -> str:
    label = str(card.get("label") or "")
    kind = str(card.get("kind") or "")
    pair = card.get("pair")
    winner = card.get("winner")

    if kind in {"map", "match"} and winner in {1, 2}:
        win_name = card.get("team1") if winner == 1 else card.get("team2")
        other = card.get("team2") if winner == 1 else card.get("team1")
        icon = "🏆" if kind == "match" else "🗺"
        pair_str = f"<code>{h(pair[0])}</code>–<code>{h(pair[1])}</code>" if pair else ""
        head = f"{icon} <b>{h(label)}</b> · <b>{h(win_name or '?')}</b> {pair_str} 对 {h(other or '?')}".strip()
    else:
        icon = "⏱" if kind == "halftime" else ("⚔️" if kind in {"preview", "soon"} else "🔴")
        t1 = h(card.get("team1") or "?")
        t2 = h(card.get("team2") or "?")
        if pair:
            head = f"{icon} <b>{h(label)}</b>  {t1} <code>{h(pair[0])}</code>–<code>{h(pair[1])}</code> {t2}"
        else:
            head = f"{icon} <b>{h(label)}</b>  {t1} vs {t2}"

    lines = [head]

    # Blockquote for map breakdown and round details
    quote_bits = []
    extra = (card.get("map_score") or "").strip()
    if extra:
        quote_bits.append(h(extra))
    note = _map_caption(list(card.get("map_rows") or []))
    if note:
        quote_bits.append(h(note))
    if quote_bits:
        lines.append(f"<blockquote>{' · '.join(quote_bits)}</blockquote>")

    # Meta footer line
    footer_bits = []
    event = (card.get("event") or "").strip()
    if event:
        tier = tier_label(classify_tier(event))
        footer_bits.append(f"<b>{h(tier)}</b> {h(event)}")
    clock = card.get("clock") or ""
    if clock:
        footer_bits.append(f"<code>{h(clock)} UTC+8</code>")
    link = _link(str(row.get("url") or ""))
    if link:
        footer_bits.append(link)
    if footer_bits:
        lines.append(" · ".join(footer_bits))

    return "\n".join(lines)


def _score_notice(
    kind: str,
    row: dict,
    when: datetime | None,
    score: str,
    cfg: RemindConfig,
    *,
    winners: list[int] | None = None,
    winner: int = 0,
    rounds: tuple[int, int] | None = None,
    map_index: int = -1,
) -> Notice:
    mid = str(row.get("id") or "")
    if kind == "preview":
        key = f"m:{mid}:preview"
    elif kind == "halftime":
        key = f"m:{mid}:halftime:{map_index}"
    elif kind == "map":
        key = f"m:{mid}:map:{map_index}"
    elif kind == "match":
        key = f"m:{mid}:match"
    else:
        key = f"m:{mid}:score:{feed_sig(row)}"
    card = _match_card(kind, row, when, score, winners=winners, winner=winner, rounds=rounds)
    return Notice(key, _match_caption(card, row), card, mid, score_lane(row, cfg), row=row)


def current_match_notice(row: dict, cfg: RemindConfig) -> Notice:
    """Build the latest score Notice for an ongoing or recently finished match."""
    score = score_text(row)
    names = _map_names(row)
    winners = _parse_winners(str(row.get("map_winners") or ""), len(names))
    rounds = _pair(score)
    if _clinched(row, winners, rounds):
        kind = "match"
        tally = _series_tally(row, winners)
        if tally[0] > tally[1]:
            win_side = 1
        elif tally[1] > tally[0]:
            win_side = 2
        elif rounds and rounds[0] != rounds[1]:
            win_side = 1 if rounds[0] > rounds[1] else 2
        else:
            win_side = 0
    else:
        kind = "score" if _real_score(score) else "preview"
        win_side = 0
    return _score_notice(kind, row, start_at(row), score or "0-0", cfg, winners=winners, winner=win_side, rounds=rounds)


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
    if hours <= DAY_LEFT_HOURS and window > DAY_LEFT_HOURS:
        return "day"
    return "days"


def _event_html(ev: dict, now: datetime, stage: str) -> str:
    """Caption under the card: name, countdown, link. The picture holds the rest."""
    del stage
    hours = _hours_left(ev, now) or 0
    lines = [
        f"<b>{h(ev.get('name') or '')}</b>",
        h(remain_text(hours)),
    ]
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
        "logo_small_url": ev.get("logo_small_url") or "",
        "flag": country_code_to_emoji(str(ev.get("country_code") or "")),
        "location": (ev.get("location") or "").strip(),
        "clock": clock,
        "remain": remain_text(hours),
        "final": stage == "hours",
    }


def _zero_row(row: dict) -> dict:
    item = dict(row)
    item["score1"] = "0"
    item["score2"] = "0"
    return item


def _snapshot_match(
    row: dict,
    *,
    opened: bool,
    soon: bool,
    score: str,
    live: bool,
    previewed: bool,
    map_winners: str = "",
    match_sent: bool = False,
    halftimes: str = "",
    missed: int = 0,
) -> dict:
    held = _pair(score)
    score1 = str(held[0]) if held else (row.get("score1") or "")
    score2 = str(held[1]) if held else (row.get("score2") or "")
    return {
        "opened": opened,
        "soon": soon,
        "live": bool(live),
        "previewed": bool(previewed),
        "score": score,
        "team1": row.get("team1") or "",
        "team2": row.get("team2") or "",
        "team1_id": row.get("team1_id") or "",
        "team2_id": row.get("team2_id") or "",
        "team1_logo": row.get("team1_logo") or "",
        "team2_logo": row.get("team2_logo") or "",
        "event_id": row.get("event_id") or "",
        "event_logo": row.get("event_logo") or "",
        "event": row.get("event") or "",
        "stars": row.get("stars") or "",
        "url": row.get("url") or "",
        "time": row.get("time") or "",
        "unix": row.get("unix") or "",
        "score1": score1,
        "score2": score2,
        "format": row.get("format") or "",
        "maps": row.get("maps") or "",
        "map_index": row.get("map_index") or "",
        "won1": row.get("won1") or "",
        "won2": row.get("won2") or "",
        "map_rounds": row.get("map_rounds") or "",
        "map_winners": map_winners,
        "match_sent": bool(match_sent),
        "halftimes": halftimes,
        "missed": int(missed),
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
        lines.append(f"<b>{h(tier_label(classify_tier(event)))}</b>")
        lines.append(f"<b>{h(event)}</b>")
        if eid:
            lines.append(f"<code>{h(eid)}</code>")
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
EVENT_POLL = 3600.0
START_LEAD = 45 * 60
DIGEST_LEAD = 20 * 60
# "还有 1 天" is the copy while more than 24 hours and at most 48 hours remain.
DAY_LEFT_HOURS = 48.0
# Event cards go out on the clock, twice a day, while the event is in the window.
EVENT_MORNING = 9
EVENT_EVENING = 18


def _as_cst(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=CST)
    return now.astimezone(CST)


def due_event_bells(now: datetime) -> list[tuple[str, str]]:
    """09:00 and 18:00 slots that have opened, oldest first.

    Only the latest two are kept, so a long outage does not replay a week.
    A slot stays due until it is sent, including after midnight.
    """
    now = _as_cst(now)
    found: list[tuple[datetime, str, str]] = []
    for shift in (1, 0):
        day = now - timedelta(days=shift)
        for hour in (EVENT_MORNING, EVENT_EVENING):
            at = day.replace(hour=hour, minute=0, second=0, microsecond=0)
            if at <= now:
                found.append((at, at.strftime("%Y-%m-%d"), f"{hour:02d}"))
    found.sort()
    return [(day, hour) for _at, day, hour in found[-2:]]


def _slot_at(day: str, hour: str) -> datetime:
    return datetime.strptime(f"{day} {hour}", "%Y-%m-%d %H").replace(tzinfo=CST)


def _upcoming_event_bell(now: datetime) -> datetime:
    now = now.astimezone(CST)
    best: datetime | None = None
    for shift in (0, 1):
        day = (now + timedelta(days=shift)).replace(minute=0, second=0, microsecond=0)
        for hour in (EVENT_MORNING, EVENT_EVENING):
            at = day.replace(hour=hour)
            if at > now and (best is None or at < best):
                best = at
    return best or now + timedelta(hours=1)


def current_event_notices(events: list[dict], now: datetime, cfg: RemindConfig) -> list[Notice]:
    """In-window Major/T1 cards as of now. Does not record a bell."""
    now = _as_cst(now)
    due = [ev for ev in events if event_stage(ev, now, cfg)]
    due.sort(key=lambda ev: (int(ev.get("start_ts") or 0), str(ev.get("id") or "")))
    notes: list[Notice] = []
    for ev in due:
        eid = str(ev.get("id") or "")
        stage = event_stage(ev, now, cfg)
        notes.append(
            Notice(
                f"e:{eid}:now",
                _event_html(ev, now, stage),
                _event_card(ev, now, stage),
            )
        )
    return notes


def _apply_event_bells(
    base: dict,
    events: list[dict],
    now: datetime,
    cfg: RemindConfig,
    notes: list[Notice],
    *,
    seed: bool,
) -> None:
    slots = due_event_bells(now)
    if not slots:
        return
    # The first events poll only records stages. Leave these slots open.
    if seed:
        return
    # No bell book yet: this process just learned the clock. Mark the open
    # slots and show one card to the admins. Do not catch the groups up.
    if "event_bells" not in base:
        sent: dict = {}
        for day, hour in slots:
            done = {str(x) for x in (sent.get(day) or [])}
            done.add(hour)
            sent[day] = sorted(done)
        base["event_bells"] = sent
        if cfg.event_watch:
            for note in current_event_notices(events, now, cfg):
                notes.append(
                    Notice(note.key, note.html, note.card, admins_only=True)
                )
        return
    sent = dict(base.get("event_bells") or {})
    pending: list[tuple[str, str]] = []
    for day, hour in slots:
        done = {str(x) for x in (sent.get(day) or [])}
        if hour not in done:
            pending.append((day, hour))
    if not pending:
        return
    for day, hour in pending:
        done = {str(x) for x in (sent.get(day) or [])}
        done.add(hour)
        sent[day] = sorted(done)
    if len(sent) > 14:
        for old in sorted(sent)[:-14]:
            sent.pop(old, None)
    base["event_bells"] = sent
    if not cfg.event_watch:
        return
    now = _as_cst(now)
    for day, hour in pending:
        at = _slot_at(day, hour)
        due = [ev for ev in events if event_stage(ev, at, cfg) and event_stage(ev, now, cfg)]
        due.sort(key=lambda ev: (int(ev.get("start_ts") or 0), str(ev.get("id") or "")))
        for ev in due:
            eid = str(ev.get("id") or "")
            stage = event_stage(ev, now, cfg)
            notes.append(
                Notice(
                    f"e:{eid}:{day}:{hour}",
                    _event_html(ev, now, stage),
                    _event_card(ev, now, stage),
                )
            )


def _event_boundary_wait(events: list[dict] | None, cfg: RemindConfig, now: datetime) -> float | None:
    """Seconds until the next Major/T1 stage: enter window, 1 day, then N hours."""
    if not cfg.event_watch or not events:
        return None
    marks = [float(cfg.event_days * 24)]
    if cfg.event_days * 24 > DAY_LEFT_HOURS:
        marks.append(DAY_LEFT_HOURS)
    if cfg.event_hours > 0:
        marks.append(float(cfg.event_hours))
    marks = sorted(set(marks), reverse=True)
    best: float | None = None
    for ev in events:
        if ev.get("live"):
            continue
        if classify_tier(str(ev.get("name") or "")) not in {"Major", "T1"}:
            continue
        hours = _hours_left(ev, now)
        if hours is None or hours <= 0:
            continue
        for mark in marks:
            if hours > mark:
                secs = (hours - mark) * 3600.0
                if best is None or secs < best:
                    best = secs
                break
    return best


def choose_poll_wait(
    rows: list[dict],
    cfg: RemindConfig,
    now: datetime,
    digests: dict | None,
    events: list[dict] | None = None,
    event_bells: dict | None = None,
) -> float:
    """Seconds until the next matches-list fetch.

    0 means a match is live: the caller uses the 3–5s clock.
    Two minutes when a watched match is about to start, or a digest is due.
    Otherwise sleep until the next lead. Event bells are checked at least hourly
    so a missed 09:00 or 18:00 is at most an hour late. Match-only quiet is six hours.
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
        if match_allowed(row, cfg)
        and str(row.get("id") or "") not in cfg.ignored
        and lane_open(row, cfg)
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
            until = (nxt - now).total_seconds()
            # Inside the lead, sleep until the bell. A 60s floor here used to
            # land in the gap after the lead and then take the 6-hour nap,
            # so 10:00 and 20:00 never ran.
            if 0 < until <= DIGEST_LEAD:
                wakes.append(until)
            elif until > DIGEST_LEAD:
                wakes.append(until - DIGEST_LEAD)
        sent_bells = event_bells or {}
        for day, hour in due_event_bells(now):
            done = {str(x) for x in (sent_bells.get(day) or [])}
            if hour not in done:
                soon = True
                break
        nxt_bell = _upcoming_event_bell(now)
        until_bell = (nxt_bell - now).total_seconds()
        if 0 < until_bell <= DIGEST_LEAD:
            wakes.append(until_bell)
        elif until_bell > DIGEST_LEAD:
            wakes.append(until_bell - DIGEST_LEAD)
        boundary = _event_boundary_wait(events, cfg, now)
        if boundary is not None and boundary > 0:
            wakes.append(boundary)
    if soon:
        return SOON_POLL
    wait = min(wakes)
    if wait < 60.0:
        return max(1.0, wait)
    cap = EVENT_POLL if cfg.event_watch else QUIET_POLL
    return min(wait, cap)


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
    # The first poll only records match scores. Leave this slot open so a
    # restart inside the window can still send it on the next pass.
    if seed:
        return
    done.add(hour)
    sent[key] = sorted(done)
    # Keep a few slates so the file does not grow without bound.
    if len(sent) > 14:
        for old in sorted(sent)[:-14]:
            sent.pop(old, None)
    base["digests"] = sent
    if not cfg.event_watch:
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
                row = cache_match_score({}, row)
                live = row.get("live") == "1"
                score = score_text(row)
                winners = merge_map_winners({}, row, _pair(score))
                seeded[mid] = _snapshot_match(
                    row,
                    opened=False,
                    soon=live,
                    score=score,
                    live=live,
                    previewed=live,
                    map_winners=_winners_text(winners),
                    match_sent=_clinched(row, winners, _pair(score)),
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
                row = cache_match_score(old, row)
                live = row.get("live") == "1"
                score = score_text(row)
                old_score = str(old.get("score") or "")
                start = start_at(row)
                opened = bool(old.get("opened"))
                soon_sent = bool(old.get("soon")) or live
                previewed = bool(old.get("previewed"))
                speak = _speak(cfg, mid, base)
                became_live = known and live and "live" in old and not old.get("live")
                audible = speak and lane_open(row, cfg)
                held = False
                pending = ""
                if became_live and not previewed:
                    if _real_score(score):
                        pending = "score"
                        opened = True
                    else:
                        pending = "preview"
                        opened = True
                        score = "0-0"
                    previewed = True
                elif known and score != old_score:
                    if old_score and not accept_round_score(old, row):
                        held = True
                        score = old_score
                    elif _real_score(score):
                        pending = "score"
                        opened = True
                view = dict(row)
                if held:
                    view["score1"] = old.get("score1") or ""
                    view["score2"] = old.get("score2") or ""
                    view["won1"] = old.get("won1") or ""
                    view["won2"] = old.get("won2") or ""
                    view["map_index"] = old.get("map_index") or ""
                    view["maps"] = old.get("maps") or row.get("maps") or ""
                rounds = _pair(score)
                winners = merge_map_winners(old if known else {}, view, None if held else rounds)
                match_sent = bool(old.get("match_sent"))
                halftimes = str(old.get("halftimes") or "")
                ht_set = {x.strip() for x in halftimes.split(",") if x.strip()}
                current_map_idx = str(view.get("map_index") or "0")
                win_side = 0
                map_at = int(current_map_idx) if current_map_idx.isdigit() else -1
                if not known:
                    pending = ""
                    if _clinched(view, winners, None if held else rounds):
                        match_sent = True
                    if rounds and (rounds[0] + rounds[1] >= 12):
                        ht_set.add(current_map_idx)
                elif pending != "preview" and not match_sent and not held and _clinched(view, winners, rounds):
                    pending = "match"
                    opened = True
                    tally = _series_tally(view, winners)
                    if tally[0] > tally[1]:
                        win_side = 1
                    elif tally[1] > tally[0]:
                        win_side = 2
                    elif rounds and rounds[0] != rounds[1]:
                        win_side = 1 if rounds[0] > rounds[1] else 2
                elif pending != "preview" and not match_sent and not held:
                    fresh = _fresh_wins(old, winners)
                    if fresh:
                        pending = "map"
                        opened = True
                        map_at = fresh[-1]
                        win_side = winners[map_at]
                    elif rounds and (rounds[0] + rounds[1] == 12) and current_map_idx not in ht_set:
                        pending = "halftime"
                        opened = True
                        ht_set.add(current_map_idx)
                if pending == "score" and match_sent:
                    pending = ""
                if pending == "match":
                    match_sent = True
                if pending and audible:
                    if pending == "preview":
                        shown = _zero_row(view)
                        notes.append(_score_notice("preview", shown, start, "0-0", cfg, winners=winners))
                    else:
                        notes.append(
                            _score_notice(
                                pending,
                                view,
                                start,
                                score,
                                cfg,
                                winners=winners,
                                winner=win_side,
                                rounds=rounds,
                                map_index=map_at,
                            )
                        )
                if live:
                    soon_sent = True
                    previewed = True
                nxt[mid] = _snapshot_match(
                    view,
                    opened=opened,
                    soon=soon_sent,
                    score=score or str(old.get("score") or ""),
                    live=live,
                    previewed=previewed,
                    map_winners=_winners_text(winners),
                    match_sent=match_sent,
                    halftimes=",".join(sorted(ht_set)),
                    missed=0,
                )
                quiet.discard(mid)
            for mid, old in prev.items():
                if mid in seen:
                    continue
                if not old.get("opened"):
                    continue

                # Anti-flapping: when matches list was fetched successfully, a missing match
                # may be a transient scraping blip or Cloudflare cache desync between requests.
                # Hold the match in state for up to 2 polls before evicting.
                missed = int(old.get("missed") or 0) + 1
                if len(matches) > 0 and missed < 3:
                    nxt[mid] = dict(old, missed=missed)
                    continue

                row = {
                    "id": mid,
                    "team1": old.get("team1"),
                    "team2": old.get("team2"),
                    "team1_id": old.get("team1_id"),
                    "team2_id": old.get("team2_id"),
                    "team1_logo": old.get("team1_logo"),
                    "team2_logo": old.get("team2_logo"),
                    "event_id": old.get("event_id"),
                    "event_logo": old.get("event_logo"),
                    "event": old.get("event"),
                    "stars": old.get("stars"),
                    "url": old.get("url"),
                    "time": old.get("time"),
                    "unix": old.get("unix"),
                    "score1": old.get("score1"),
                    "score2": old.get("score2"),
                    "format": old.get("format"),
                    "maps": old.get("maps"),
                    "map_index": old.get("map_index"),
                    "won1": old.get("won1"),
                    "won2": old.get("won2"),
                    "map_winners": old.get("map_winners") or "",
                    "halftimes": old.get("halftimes") or "",
                }
                if not old.get("match_sent") and _speak(cfg, mid, base) and lane_open(row, cfg):
                    winners = _parse_winners(str(old.get("map_winners") or ""), len(_map_names(row)))
                    rounds = _pair(str(old.get("score") or ""))
                    tally = _series_tally(row, winners)
                    if tally[0] > tally[1]:
                        win_side = 1
                    elif tally[1] > tally[0]:
                        win_side = 2
                    elif rounds and rounds[0] != rounds[1]:
                        win_side = 1 if rounds[0] > rounds[1] else 2
                    else:
                        win_side = 0

                    old_score_str = str(old.get("score") or "").strip()
                    # A match cannot be announced as "Match winner" if:
                    # 1) Neither team won (win_side == 0)
                    # 2) Score was 0-0 / unstarted / not real score and no maps won
                    has_winner = win_side in {1, 2}
                    has_progress = _real_score(old_score_str) or any(winners)
                    if has_winner and has_progress:
                        notes.append(
                            _score_notice(
                                "match",
                                row,
                                start_at(row),
                                old_score_str,
                                cfg,
                                winners=winners,
                                winner=win_side,
                                rounds=rounds,
                            )
                        )
                quiet.discard(mid)
            base["matches"] = nxt
            base["quiet_ids"] = sorted(quiet)
            base["quiet_all"] = False
            _apply_digest(base, matches, now, cfg, notes, seed=False)

    if events is not None:
        stages: dict[str, str] = {}
        for ev in events:
            eid = str(ev.get("id") or "")
            if not eid:
                continue
            stage = event_stage(ev, now, cfg)
            if not stage:
                continue
            stages[eid] = stage
        _apply_event_bells(
            base,
            events,
            now,
            cfg,
            notes,
            seed=not base.get("events_seeded"),
        )
        base["events"] = stages
        base["events_seeded"] = True

    return base, notes
