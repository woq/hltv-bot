from __future__ import annotations

import json
import logging
from typing import Any

live_log = logging.getLogger("hltv_bot.live")


def _as_player_list(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        inner = raw.get("players")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
        vals = [v for v in raw.values() if isinstance(v, dict)]
        if vals and any("deaths" in v or "kills" in v or "score" in v for v in vals):
            return vals
    return []


def _side_players(board: dict[str, Any], *keys: str) -> list[dict[str, Any]]:
    for key in keys:
        if key in board:
            lst = _as_player_list(board[key])
            if lst:
                return lst
    return []


def _num(p: dict[str, Any], *keys: str) -> float:
    for key in keys:
        if key in p and p[key] is not None:
            try:
                return float(p[key])
            except (TypeError, ValueError):
                continue
    return 0.0


def _players(side: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for p in side or []:
        nick = p.get("nick") or p.get("name") or p.get("dbName") or p.get("playerName") or "?"
        out.append(
            {
                "nick": nick,
                "kills": int(_num(p, "kills", "score")),
                "assists": int(_num(p, "assists", "assistsUnconfirmed")),
                "deaths": int(_num(p, "deaths")),
                "adr": float(_num(p, "damagePrRound", "adr", "damage")),
            }
        )
    return out


_ROUND_BREAK = frozenset({"round_start", "round_over", "round_over_ct", "round_over_t"})
_ROUND_OVER = frozenset({"round_over", "round_over_ct", "round_over_t"})

_WIN_REASON = {
    "Bomb_Defused": "defuse",
    "Target_Bombed": "bomb",
    "Target_Saved": "time",
    "CTs_Win": "elimination",
    "Terrorists_Win": "elimination",
}


def _winner_side(winner: object) -> str:
    w = str(winner or "").upper()
    if w in ("CT", "CTS", "COUNTERTERRORIST", "COUNTER-TERRORIST"):
        return "CT"
    if w in ("T", "TERRORIST", "TERRORISTS"):
        return "T"
    return str(winner or "")


def _round_over_entry(
    *,
    winner: object,
    win_type: object = "",
    ct_score: object = None,
    t_score: object = None,
) -> dict[str, Any]:
    side = _winner_side(winner)
    reason = _WIN_REASON.get(str(win_type or ""), str(win_type or "").replace("_", " ").strip())
    score = ""
    if ct_score is not None and t_score is not None:
        score = f"{ct_score}-{t_score}"
    bits = ["Round over", side, reason, score]
    detail = " · ".join(x for x in bits if x)
    out: dict[str, Any] = {
        "type": "round_over_ct" if side == "CT" else "round_over_t",
        "killer": "Round",
        "text": detail,
        "detail": detail,
        "winner": side,
        "win_type": str(win_type or ""),
    }
    if ct_score is not None:
        out["ct_score"] = ct_score
    if t_score is not None:
        out["t_score"] = t_score
    return out


def _round_start_entry() -> dict[str, Any]:
    return {"type": "round_start", "killer": "Round", "text": "start", "detail": "start"}


def _board_map_scores(board: dict[str, Any] | None) -> tuple[int | None, int | None]:
    if not board:
        return None, None
    ct = board.get("ctScore")
    if ct is None:
        ct = board.get("counterTerroristScore")
    if ct is None:
        ct = board.get("ctTeamScore")
    t = board.get("tScore")
    if t is None:
        t = board.get("terroristScore")
    if t is None:
        t = board.get("tTeamScore")
    try:
        return int(ct), int(t)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None, None


def _last_history_win(board: dict[str, Any]) -> tuple[str, str]:
    """Winner side + winType from the latest non-lost match-history round."""
    latest: tuple[int, str, str] | None = None
    for side, key in (("CT", "ctMatchHistory"), ("T", "terroristMatchHistory")):
        hist = board.get(key) or {}
        if not isinstance(hist, dict):
            continue
        for half in ("firstHalf", "secondHalf"):
            rows = hist.get(half) or []
            if not isinstance(rows, list):
                continue
            for r in rows:
                if not isinstance(r, dict):
                    continue
                typ = str(r.get("type") or "")
                if not typ or typ.lower() == "lost":
                    continue
                try:
                    n = int(r.get("roundOrdinal") or 0)
                except (TypeError, ValueError):
                    n = 0
                if latest is None or n >= latest[0]:
                    latest = (n, side, typ)
    if not latest:
        return "", ""
    return latest[1], latest[2]


def match_history(board: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Round-by-round winners from ct/t matchHistory (HLTV scoreboard)."""
    if not board:
        return []
    by_n: dict[int, dict[str, Any]] = {}
    for side, key in (("CT", "ctMatchHistory"), ("T", "terroristMatchHistory")):
        hist = board.get(key) or {}
        if not isinstance(hist, dict):
            continue
        for half in ("firstHalf", "secondHalf"):
            rows = hist.get(half) or []
            if not isinstance(rows, list):
                continue
            for r in rows:
                if not isinstance(r, dict):
                    continue
                typ = str(r.get("type") or "")
                if not typ or typ.lower() == "lost":
                    continue
                try:
                    n = int(r.get("roundOrdinal"))
                except (TypeError, ValueError):
                    continue
                by_n[n] = {
                    "n": n,
                    "winner": side,
                    "winType": typ,
                    "alive": r.get("survivingPlayers"),
                }
    return [by_n[k] for k in sorted(by_n)]


def _event_id(item: dict[str, Any]) -> str | None:
    for v in item.values():
        if isinstance(v, dict) and v.get("eventId") is not None:
            return str(v.get("eventId"))
    return None


def _fallback_key(item: dict[str, Any]) -> str:
    return json.dumps(item, sort_keys=True, separators=(",", ":"), default=str)


def _semantic_key(entry: dict[str, Any]) -> str | None:
    """Stable identity for a log row, ignoring eventId / coordinates / flasher."""
    typ = entry.get("type")
    if typ == "kill":
        return "|".join(
            (
                "k",
                str(entry.get("killer") or ""),
                str(entry.get("victim") or ""),
                str(entry.get("weapon") or ""),
                "1" if entry.get("headshot") else "0",
            )
        )
    if typ == "bomb":
        return "|".join(
            (
                "b",
                str(entry.get("killer") or ""),
                str(entry.get("detail") or entry.get("text") or ""),
            )
        )
    if typ == "assist":
        return "|".join(
            (
                "a",
                str(entry.get("killer") or ""),
                str(entry.get("victim") or ""),
                str(entry.get("kill_event_id") or ""),
            )
        )
    if typ in {"round_over", "round_over_ct", "round_over_t"}:
        return "|".join(
            (
                "e",
                str(entry.get("detail") or entry.get("text") or ""),
                str(entry.get("ct_score", "")),
                str(entry.get("t_score", "")),
            )
        )
    if typ == "round_start":
        return None
    text = str(entry.get("text") or "")
    return f"o|{text}" if text else None


def _kill_pair(entry: dict[str, Any]) -> tuple[str, str] | None:
    if entry.get("type") != "kill":
        return None
    killer = str(entry.get("killer") or "")
    victim = str(entry.get("victim") or "")
    if killer and victim:
        return killer, victim
    return None


def _this_round_entries(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entry in log:
        if entry.get("type") in _ROUND_BREAK:
            break
        out.append(entry)
    return out


def _pairs_this_round(log: list[dict[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for entry in _this_round_entries(log):
        pair = _kill_pair(entry)
        if pair:
            pairs.add(pair)
    return pairs


def _coerce_round(board: dict[str, Any]) -> int | None:
    raw = board.get("currentRound") if board else None
    if raw is None:
        raw = board.get("round") if board else None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def mark_new_round(
    feed: list[dict[str, Any]],
    board: dict[str, Any],
    prev_round: int | None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Insert a round_start when scoreboard currentRound changes (half / next map)."""
    n = _coerce_round(board)
    if n is None:
        return feed, prev_round
    if prev_round is not None and n != prev_round:
        if not feed or feed[0].get("type") != "round_start":
            feed = [_round_start_entry(), *feed]
            live_log.debug("round marker %s -> %s", prev_round, n)
    return feed, n


def mark_round_over(
    feed: list[dict[str, Any]],
    board: dict[str, Any],
    prev_ct: int | None,
    prev_t: int | None,
) -> tuple[list[dict[str, Any]], int | None, int | None]:
    """Insert a round_over when the map score ticks and log missed RoundEnd."""
    ct, t = _board_map_scores(board)
    if ct is None or t is None:
        return feed, prev_ct, prev_t
    if prev_ct is None or prev_t is None:
        return feed, ct, t
    if ct == prev_ct and t == prev_t:
        return feed, ct, t
    if feed and feed[0].get("type") in _ROUND_OVER:
        top = feed[0]
        if top.get("ct_score") in (None, ct) and top.get("t_score") in (None, t):
            return feed, ct, t
    winner = "CT" if ct > prev_ct else "T"
    hist_side, hist_type = _last_history_win(board)
    if hist_side:
        winner = hist_side
    entry = _round_over_entry(
        winner=winner,
        win_type=hist_type,
        ct_score=ct,
        t_score=t,
    )
    live_log.debug("round over from scoreboard %s-%s winner=%s", ct, t, winner)
    return [entry, *feed], ct, t


def format_log_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if "Kill" in item:
        k = item["Kill"]
        weapon = (k.get("weapon") or "").lower()
        killer = k.get("killerNick") or k.get("killerName") or ""
        victim = k.get("victimNick") or k.get("victimName") or ""
        out = {
            "type": "kill",
            "killer": killer,
            "victim": victim,
            "text": f"{killer} {victim}".strip(),
            "weapon": weapon,
            "headshot": bool(k.get("headShot")),
            "assist": False,
        }
        eid = _event_id(item)
        if eid:
            out["event_id"] = eid
        return out
    if "Assist" in item:
        a = item["Assist"]
        nick = a.get("assisterNick") or a.get("assisterName") or ""
        victim = a.get("victimNick") or a.get("victimName") or ""
        out = {
            "type": "assist",
            "killer": nick,
            "victim": victim,
            "text": f"{nick} assist {victim}".strip(),
            "detail": f"assist {victim}".strip(),
            "assist": True,
        }
        kid = a.get("killEventId")
        if kid is not None:
            out["kill_event_id"] = str(kid)
        return out
    if "BombPlanted" in item:
        b = item["BombPlanted"]
        site = str(b.get("bombSite") or "").strip()
        nick = b.get("playerNick") or b.get("playerName") or ""
        action = f"planted {site}".strip() if site else "planted"
        return {
            "type": "bomb",
            "killer": nick,
            "text": action,
            "detail": action,
        }
    if "BombDefused" in item:
        b = item["BombDefused"]
        nick = b.get("playerNick") or b.get("playerName") or ""
        return {
            "type": "bomb",
            "killer": nick,
            "text": "defused",
            "detail": "defused",
        }
    if "RoundStart" in item or "RoundStarted" in item or "Restart" in item:
        return _round_start_entry()
    if "RoundEnd" in item:
        r = item["RoundEnd"]
        return _round_over_entry(
            winner=r.get("winner") or "",
            win_type=r.get("winType") or r.get("reason") or "",
            ct_score=r.get("counterTerroristScore"),
            t_score=r.get("terroristScore"),
        )
    if "Suicide" in item:
        s = item["Suicide"]
        nick = s.get("playerNick") or s.get("nick") or ""
        return {"type": "suicide", "text": f"{nick} suicide"}
    if len(item) == 1:
        kind, payload = next(iter(item.items()))
        if kind in {
            "PlayerJoin",
            "PlayerQuit",
            "MatchStarted",
            "MatchStart",
            "MatchOver",
            "Reconnect",
            "Disconnect",
            "Assist",
        }:
            return None
        if isinstance(payload, dict):
            nick = payload.get("playerNick") or payload.get("nick") or ""
            return {"type": "other", "text": f"{kind} {nick}".strip()}
        return {"type": "other", "text": str(kind)}
    return None


def _log_items(incoming: Any) -> list[dict[str, Any]] | None:
    block = incoming
    if isinstance(incoming, dict) and "log" in incoming:
        block = incoming["log"]
    if isinstance(block, list):
        return [x for x in block if isinstance(x, dict)]
    if isinstance(block, dict):
        return [block]
    return None


def merge_log(existing: list[dict[str, Any]], incoming: Any) -> list[dict[str, Any]]:
    """Append new log rows.

    Connect / reconnect / half-time often re-send history in one packet.
    Skip already-seen eventId; if ids reset, skip by semantic identity.
    Same killer→victim cannot happen twice in one CS round.
    """
    items = _log_items(incoming)
    if items is None:
        return existing

    prepared: list[dict[str, Any]] = []
    for it in items:
        formatted = format_log_item(it)
        if not formatted:
            continue
        eid = formatted.get("event_id") or _event_id(it)
        if eid:
            formatted["event_id"] = eid
        elif formatted.get("type") != "round_start":
            # RoundStart 载荷经常是 {}，用 JSON 当 key 会把每回合开始并成一条。
            formatted["_raw"] = _fallback_key(it)
        prepared.append(formatted)

    if not prepared:
        return existing

    def apply_assist(rows: list[dict[str, Any]], assist: dict[str, Any]) -> bool:
        kid = str(assist.get("kill_event_id") or "")
        victim = str(assist.get("victim") or "")
        nick = str(assist.get("killer") or "")
        if not nick:
            return False
        for e in rows:
            if e.get("type") != "kill":
                continue
            if kid and str(e.get("event_id") or "") == kid:
                e["assister"] = nick
                e["assist"] = True
                return True
        if kid:
            return False
        for e in _this_round_entries(rows):
            if e.get("type") != "kill":
                continue
            if victim and str(e.get("victim") or "") == victim and not e.get("assister"):
                e["assister"] = nick
                e["assist"] = True
                return True
        return False

    def attach_pending_assist(kill: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        kid = str(kill.get("event_id") or "")
        victim = str(kill.get("victim") or "")
        for i, e in enumerate(rows):
            if e.get("type") != "assist":
                continue
            match = False
            if kid and str(e.get("kill_event_id") or "") == kid:
                match = True
            elif not e.get("kill_event_id") and victim and str(e.get("victim") or "") == victim:
                match = True
            if match:
                kill["assister"] = e.get("killer") or ""
                kill["assist"] = True
                rows.pop(i)
                return

    def replace_synth_round_over(rows: list[dict[str, Any]], entry: dict[str, Any]) -> bool:
        if entry.get("type") not in _ROUND_OVER or not rows:
            return False
        top = rows[0]
        if top.get("type") not in _ROUND_OVER:
            return False
        if top.get("ct_score") not in (None, entry.get("ct_score")):
            return False
        if top.get("t_score") not in (None, entry.get("t_score")):
            return False
        rows[0] = entry
        return True

    seen_ids_all = {str(x.get("event_id")) for x in existing if x.get("event_id")}
    seen_ids_round = {
        str(x.get("event_id")) for x in _this_round_entries(existing) if x.get("event_id")
    }
    seen_fb = {str(x.get("_raw")) for x in _this_round_entries(existing) if x.get("_raw")}
    seen_sem = {k for x in existing if (k := _semantic_key(x))}
    incoming_ids = [str(x.get("event_id")) for x in prepared if x.get("event_id")]
    if existing and incoming_ids and all(i in seen_ids_round for i in incoming_ids):
        live_log.debug("log replay skipped n=%s", len(prepared))
        return existing
    if (
        existing
        and incoming_ids
        and len(incoming_ids) >= 4
        and all(i in seen_ids_all for i in incoming_ids)
    ):
        live_log.debug("log history replay skipped n=%s", len(prepared))
        return existing

    kill_rows = [x for x in prepared if x.get("type") == "kill"]
    kill_matched = sum(1 for x in kill_rows if (k := _semantic_key(x)) and k in seen_sem)
    replay = (
        bool(existing)
        and len(kill_rows) >= 4
        and kill_matched >= max(2, len(kill_rows) // 2)
    )
    if replay:
        live_log.debug("log dump replay kills=%s matched=%s", len(kill_rows), kill_matched)

    out = list(existing)
    pairs = _pairs_this_round(out)
    added = 0
    for formatted in prepared:
        eid = formatted.get("event_id")
        if eid and eid in seen_ids_round:
            continue
        fb = formatted.get("_raw")
        if fb and fb in seen_fb:
            continue
        sem = _semantic_key(formatted)
        if replay and sem and sem in seen_sem:
            continue
        pair = _kill_pair(formatted)
        if pair and pair in pairs:
            continue
        if formatted.get("type") == "assist" and apply_assist(out, formatted):
            continue
        if formatted.get("type") == "kill":
            attach_pending_assist(formatted, out)
        if replace_synth_round_over(out, formatted):
            continue
        if eid:
            seen_ids_round.add(str(eid))
        if fb:
            seen_fb.add(str(fb))
        if sem:
            seen_sem.add(sem)
        out.insert(0, formatted)
        added += 1
        if formatted.get("type") in _ROUND_BREAK:
            pairs = set()
            seen_fb = set()
            seen_ids_round = set()
        elif pair:
            pairs.add(pair)
    if added:
        live_log.debug("log merged +%s total=%s", added, len(out))
    return out[:80]


def patch_board_from_log(board: dict[str, Any], incoming: Any) -> dict[str, Any]:
    """RoundEnd carries the new map score; keep the board in sync if scoreboard is stale."""
    items = _log_items(incoming)
    if items is None:
        return board
    last: dict[str, Any] | None = None
    for it in items:
        r = it.get("RoundEnd") if isinstance(it, dict) else None
        if isinstance(r, dict):
            last = r
    if not last:
        return board
    patched = dict(board) if board else {}
    if last.get("counterTerroristScore") is not None:
        patched["counterTerroristScore"] = last.get("counterTerroristScore")
        patched["ctTeamScore"] = last.get("counterTerroristScore")
    if last.get("terroristScore") is not None:
        patched["terroristScore"] = last.get("terroristScore")
        patched["tTeamScore"] = last.get("terroristScore")
    return patched


def snapshot_from_scoreboard(
    board: dict[str, Any],
    *,
    meta: dict[str, Any] | None = None,
    log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    ct_name = board.get("ctTeamName") or board.get("ctName") or meta.get("team2") or "CT"
    t_name = board.get("tTeamName") or board.get("terroristTeamName") or meta.get("team1") or "T"
    ct_score = (
        board.get("ctScore")
        or board.get("counterTerroristScore")
        or board.get("ctTeamScore")
        or 0
    )
    t_score = (
        board.get("tScore")
        or board.get("terroristScore")
        or board.get("tTeamScore")
        or board.get("terroristTeamScore")
        or 0
    )
    try:
        ct_score = int(ct_score)
        t_score = int(t_score)
    except (TypeError, ValueError):
        ct_score, t_score = 0, 0
    round_n = board.get("currentRound") or board.get("round") or ""
    map_name = board.get("mapName") or board.get("map") or ""
    map_name = str(map_name or "").removeprefix("de_").replace("_", " ").title()
    ct_players = _side_players(
        board, "ctTeam", "ctPlayers", "counterTerrorists", "CT", "ct"
    )
    t_players = _side_players(
        board, "terroristTeam", "tPlayers", "terrorists", "TERRORIST", "t"
    )
    if not ct_players and not t_players:
        live_log.debug("scoreboard no players keys=%s", list(board.keys()))
    else:
        live_log.debug(
            "scoreboard players ct=%s t=%s",
            len(ct_players),
            len(t_players),
        )
    return {
        "live": True,
        "url": meta.get("url"),
        "team1": {"name": t_name},
        "team2": {"name": ct_name},
        "roundText": f"{round_n} - {map_name}".strip(" -"),
        "scoreText": f"{ct_score}-{t_score}",
        "ctScore": ct_score,
        "tScore": t_score,
        "teams": [
            {"name": ct_name, "players": _players(ct_players if isinstance(ct_players, list) else None)},
            {"name": t_name, "players": _players(t_players if isinstance(t_players, list) else None)},
        ],
        "history": match_history(board),
        "bombPlanted": bool(board.get("bombPlanted")),
        "frozen": bool(board.get("frozen")),
        "log": log or [],
    }
