from __future__ import annotations

from html import escape

_ROUND_BREAK = frozenset(
    {"round_start", "round_over", "round_over_ct", "round_over_t"}
)

_WEAPON = {
    "ak47": "AK-47",
    "m4a1": "M4A1",
    "m4a1_silencer": "M4A1-S",
    "m4a4": "M4A4",
    "awp": "AWP",
    "deagle": "Desert Eagle",
    "revolver": "R8 Revolver",
    "usp_silencer": "USP-S",
    "glock": "Glock-18",
    "galilar": "Galil AR",
    "famas": "FAMAS",
    "ssg08": "SSG 08",
    "sg556": "SG 553",
    "aug": "AUG",
    "mp9": "MP9",
    "mac10": "MAC-10",
    "ump45": "UMP-45",
    "mp7": "MP7",
    "mp5sd": "MP5-SD",
    "p90": "P90",
    "bizon": "PP-Bizon",
    "p250": "P250",
    "tec9": "Tec-9",
    "fiveseven": "Five-SeveN",
    "five-seven": "Five-SeveN",
    "cz75a": "CZ75-Auto",
    "elite": "Dual Berettas",
    "nova": "Nova",
    "xm1014": "XM1014",
    "mag7": "MAG-7",
    "sawedoff": "Sawed-Off",
    "m249": "M249",
    "negev": "Negev",
    "hegrenade": "HE Grenade",
    "inferno": "Incendiary",
    "molotov": "Molotov",
    "flashbang": "Flashbang",
    "smokegrenade": "Smoke",
    "decoy": "Decoy",
    "knife": "Knife",
    "knife_t": "Knife",
    "taser": "Zeus x27",
    "c4": "C4",
}

_HR = "──────────────"

_STREAK = {
    2: "2K",
    3: "🔥 3K",
    4: "💥 4K",
    5: "⭐ ACE",
}


def h(text: object) -> str:
    return escape(str(text), quote=False)


def _killer_victim(entry: dict) -> tuple[str, str]:
    killer = entry.get("killer") or ""
    victim = entry.get("victim") or ""
    if not killer or not victim:
        parts = (entry.get("text") or "").split()
        if len(parts) >= 2 and not killer:
            killer = parts[0]
        if len(parts) >= 2 and not victim:
            victim = parts[-1]
    return killer, victim


def _weapon_label(weapon: str) -> str:
    w = (weapon or "").lower().replace("weapon_", "")
    if not w:
        return ""
    if w in _WEAPON:
        return _WEAPON[w]
    return w.replace("_", " ").title()


def _this_round(log: list[dict]) -> list[dict]:
    out: list[dict] = []
    for entry in log:
        if entry.get("type") in _ROUND_BREAK:
            break
        out.append(entry)
    return out


def round_multikills(log: list[dict]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for entry in _this_round(log):
        if entry.get("type") != "kill":
            continue
        killer, _ = _killer_victim(entry)
        if killer:
            counts[killer] = counts.get(killer, 0) + 1
    ranked = [(n, c) for n, c in counts.items() if c >= 2]
    ranked.sort(key=lambda x: -x[1])
    return ranked[:3]


def round_kill_counts(log: list[dict]) -> dict[int, int]:
    """id(entry) -> 1-based kill number for that killer in the current round."""
    events = list(reversed(_this_round(log)))
    tallies: dict[str, int] = {}
    out: dict[int, int] = {}
    for entry in events:
        if entry.get("type") != "kill":
            continue
        killer, _ = _killer_victim(entry)
        if not killer:
            continue
        tallies[killer] = tallies.get(killer, 0) + 1
        out[id(entry)] = tallies[killer]
    return out


def _log_line(entry: dict, *, kill_n: int = 0) -> str | None:
    typ = entry.get("type")
    if typ == "kill":
        killer, victim = _killer_victim(entry)
        weap = _weapon_label(entry.get("weapon") or "")
        icon = "🎯" if entry.get("headshot") else "💀"
        bits = [f"{icon} <b>{h(killer)}</b> killed {h(victim)}"]
        if weap:
            bits.append(f"with {h(weap)}")
        extra = []
        if entry.get("headshot"):
            extra.append("HS")
        if kill_n >= 2:
            extra.append(_STREAK.get(kill_n, f"{kill_n}K"))
        if extra:
            bits.append(f"({h(', '.join(extra))})")
        return " ".join(bits)
    if typ in ("bomb",) or "plant" in (entry.get("text") or "").lower():
        text = entry.get("text") or ""
        if "defus" in text.lower() or "拆" in text:
            return f"🧰 {h(text)}"
        return f"💣 {h(text)}"
    if typ in _ROUND_BREAK and typ != "round_start":
        return f"🏁 {h(entry.get('text') or '回合结束')}"
    if typ == "round_start":
        return "▶️ 回合开始"
    if typ in {"quit", "suicide"}:
        return None
    text = entry.get("text") or ""
    if not text:
        return None
    return f"• {h(text)}"


def _plain(name: object, width: int) -> str:
    s = str(name or "?").replace("<", "").replace(">", "")[:width]
    return s + " " * (width - len(s))


def _mono(nick: str, k, a, d, adr, width: int = 12) -> str:
    n = str(nick)[:width]
    n = n + " " * (width - len(n))
    try:
        adr_s = f"{float(adr):.0f}"
    except (TypeError, ValueError):
        adr_s = str(adr)
    return f"{n} {int(k or 0):>2} {int(a or 0):>2} {int(d or 0):>2} {adr_s:>4}"


def format_telegram(snap: dict, *, log_limit: int = 15) -> str:
    """HLTV-style scoreboard; log keeps 2K/3K on the kill line (15 events)."""
    teams = list(snap.get("teams") or [])
    left = teams[0] if teams else {"name": (snap.get("team2") or {}).get("name") or "CT", "players": []}
    right = teams[1] if len(teams) > 1 else {"name": (snap.get("team1") or {}).get("name") or "T", "players": []}
    ct = snap.get("ctScore")
    t = snap.get("tScore")
    if ct is None or t is None:
        parts = str(snap.get("scoreText") or "0-0").replace(":", "-").split("-")
        ct, t = (parts + ["0", "0"])[:2]
    round_text = (snap.get("roundText") or "").replace(" - ", " · ")
    live = "🔴 LIVE" if snap.get("live") else "📊"
    log = snap.get("log") or []
    kill_ns = round_kill_counts(log)

    lines = [
        f"{live}  <b>{h(round_text)}</b>" if round_text else live,
        "",
        f"<b>{h(left.get('name'))}</b>   <code>{ct}</code>",
        f"<b>{h(right.get('name'))}</b>   <code>{t}</code>",
    ]

    for team in (left, right):
        players = list(team.get("players") or [])[:5]
        players.sort(key=lambda p: (-int(p.get("kills") or 0), float(p.get("adr") or 0)))
        lines.append(_HR)
        lines.append(f"<b>{h(team.get('name') or '?')}</b>")
        body = "\n".join(
            _mono(p.get("nick") or "?", p.get("kills"), p.get("assists"), p.get("deaths"), p.get("adr"))
            for p in players
        )
        if body:
            lines.append(f"<pre>             K  A  D  ADR\n{body}</pre>")
        else:
            lines.append("<i>暂无选手数据</i>")

    log_lines: list[str] = []
    for entry in log:
        line = _log_line(entry, kill_n=kill_ns.get(id(entry), 0))
        if not line:
            continue
        log_lines.append(line)
        if len(log_lines) >= log_limit:
            break
    if log_lines:
        lines.append(_HR)
        lines.append("<b>Game log</b>")
        lines.extend(log_lines)
    lines.append("<i>/bump</i>")
    text = "\n".join(lines).strip() + "\n"
    while len(text) > 3800 and log_limit > 6:
        log_limit -= 3
        return format_telegram(snap, log_limit=log_limit)
    if len(text) > 3900:
        text = text[:3890] + "\n"
    return text


def format_match_list(
    rows: list[dict],
    *,
    limit: int = 24,
    starred_only: bool = True,
) -> str:
    def star_n(r: dict) -> int:
        try:
            return int(r.get("stars") or 0)
        except (TypeError, ValueError):
            return 0

    rows = list(rows)
    if starred_only:
        rows = [r for r in rows if star_n(r) > 0]
    rows = rows[:limit]
    if not rows:
        if starred_only:
            return "没有带星级的比赛。\n发 <code>/matches all</code> 查看全部。"
        return "今天没有抓到比赛。"

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        key = (r.get("event") or "").strip() or "其它"
        grouped.setdefault(key, []).append(r)

    def event_key(item: tuple[str, list[dict]]) -> tuple:
        name, ms = item
        stars = [star_n(x) for x in ms]
        live_n = sum(1 for x in ms if x.get("live") == "1")
        return (-max(stars, default=0), -live_n, name.lower())

    def match_key(r: dict) -> tuple:
        return (-star_n(r), 0 if r.get("live") == "1" else 1)

    blocks: list[str] = []
    for event, matches in sorted(grouped.items(), key=event_key):
        matches = sorted(matches, key=match_key)
        lines = [f"<b>{h(event)}</b>"]
        for r in matches:
            n = star_n(r)
            live = r.get("live") == "1"
            clock = h(r.get("time") or ("LIVE" if live else ""))
            mark = "🔴" if live else "▫️"
            t1 = h(r.get("team1") or r.get("title") or "?")
            t2 = h(r.get("team2") or "")
            vs = f"{t1} — {t2}" if t2 else t1
            mid = h(r.get("id") or "")
            star_s = "⭐" * n if n else ""
            time_bit = f"<code>{clock}</code>  " if clock else ""
            lines.append(f"{mark} {time_bit}<b>{vs}</b>")
            tail = f"{star_s}  " if star_s else ""
            lines.append(f"{tail}<code>/watch {mid}</code>")
        blocks.append("\n".join(lines))
    hint = (
        "<i>时间 UTC+8 · /matches all 显示无星比赛</i>"
        if starred_only
        else "<i>时间 UTC+8 · /matches 只看有星赛事</i>"
    )
    blocks.append(hint)
    return "\n\n".join(blocks) + "\n"
