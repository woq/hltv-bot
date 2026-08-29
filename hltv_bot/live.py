from __future__ import annotations

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


def format_log_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if "Kill" in item:
        k = item["Kill"]
        weapon = (k.get("weapon") or "").lower()
        killer = k.get("killerNick") or k.get("killerName") or ""
        victim = k.get("victimNick") or k.get("victimName") or ""
        return {
            "type": "kill",
            "killer": killer,
            "victim": victim,
            "text": f"{killer} {victim}".strip(),
            "weapon": weapon,
            "headshot": bool(k.get("headShot")),
            "assist": False,
        }
    if "Assist" in item:
        a = item["Assist"]
        return {
            "type": "other",
            "text": f"{a.get('assisterNick')} assist {a.get('victimNick')}",
        }
    if "BombPlanted" in item:
        b = item["BombPlanted"]
        site = b.get("bombSite") or ""
        nick = b.get("playerNick") or b.get("playerName") or ""
        return {
            "type": "bomb",
            "text": f"{nick} 安包 {site}".strip(),
        }
    if "BombDefused" in item:
        b = item["BombDefused"]
        nick = b.get("playerNick") or b.get("playerName") or ""
        return {"type": "bomb", "text": f"{nick} 拆包"}
    if "RoundStart" in item or "RoundStarted" in item:
        return {"type": "round_start", "text": "回合开始"}
    if "RoundEnd" in item:
        r = item["RoundEnd"]
        winner = r.get("winner") or ""
        win_type = r.get("winType") or r.get("reason") or ""
        label = {"CT": "CT 胜", "TERRORIST": "T 胜", "T": "T 胜"}.get(str(winner), str(winner))
        reason = {
            "Bomb_Defused": "拆包",
            "Target_Bombed": "爆炸",
            "Target_Saved": "时间",
            "CTs_Win": "歼灭",
            "Terrorists_Win": "歼灭",
        }.get(str(win_type), str(win_type))
        text = "回合结束 " + " · ".join(x for x in (label, reason) if x)
        side = "ct" if str(winner).upper() in ("CT", "CTS") else "t"
        return {"type": "round_over_ct" if side == "ct" else "round_over_t", "text": text}
    if "Suicide" in item:
        s = item["Suicide"]
        nick = s.get("playerNick") or s.get("nick") or ""
        return {"type": "suicide", "text": f"{nick} 自杀"}
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


def merge_log(existing: list[dict[str, Any]], incoming: Any) -> list[dict[str, Any]]:
    block = incoming
    if isinstance(incoming, dict) and "log" in incoming:
        block = incoming["log"]
    items: list[dict[str, Any]]
    if isinstance(block, list):
        items = [x for x in block if isinstance(x, dict)]
    elif isinstance(block, dict):
        items = [block]
    else:
        return existing
    out = list(existing)
    for it in items:
        formatted = format_log_item(it)
        if formatted:
            out.insert(0, formatted)
    return out[:80]


def snapshot_from_scoreboard(
    board: dict[str, Any],
    *,
    meta: dict[str, Any] | None = None,
    log: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    meta = meta or {}
    ct_name = board.get("ctTeamName") or board.get("ctName") or meta.get("team2") or "CT"
    t_name = board.get("tTeamName") or board.get("terroristTeamName") or meta.get("team1") or "T"
    ct_score = board.get("ctScore") or board.get("counterTerroristScore") or 0
    t_score = board.get("tScore") or board.get("terroristScore") or 0
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
        "log": log or [],
    }
