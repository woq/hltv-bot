from __future__ import annotations

from html import escape

_ROUND_BREAK = frozenset(
    {"round_start", "round_over", "round_over_ct", "round_over_t"}
)

_WEAPON = {
    "ak47": "AK",
    "m4a1": "M4",
    "m4a1_silencer": "M4",
    "awp": "AWP",
    "deagle": "Deag",
    "usp_silencer": "USP",
    "glock": "Glock",
    "galilar": "Galil",
    "famas": "FAMAS",
    "ssg08": "SCOUT",
    "sg556": "SG",
    "aug": "AUG",
    "mp9": "MP9",
    "mac10": "MAC10",
    "ump45": "UMP",
    "p250": "P250",
    "tec9": "TEC9",
    "five-seven": "57",
    "cz75a": "CZ",
    "nova": "Nova",
    "xm1014": "XM",
    "mag7": "MAG7",
    "sawedoff": "Sawed",
    "m249": "M249",
    "negev": "Negev",
    "hegrenade": "HE",
    "inferno": "火",
    "molotov": "火",
    "flashbang": "闪",
    "smokegrenade": "烟",
    "decoy": "诱",
    "knife": "刀",
    "knife_t": "刀",
    "taser": "电击",
    "c4": "C4",
}

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
    return _WEAPON.get(w, w.upper() if w else "")


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


def _streak_banner(log: list[dict]) -> str:
    bits = []
    for nick, n in round_multikills(log):
        label = _STREAK.get(n, f"{n}K")
        bits.append(f"{label} <b>{h(nick)}</b>")
    if not bits:
        return ""
    return "🔥 " + "  ·  ".join(bits)


def _log_line(entry: dict) -> str | None:
    typ = entry.get("type")
    if typ == "kill":
        killer, victim = _killer_victim(entry)
        weap = _weapon_label(entry.get("weapon") or "")
        icon = "🎯" if entry.get("headshot") else "💀"
        extra = []
        if entry.get("headshot"):
            extra.append("HS")
        if entry.get("assist"):
            extra.append("A")
        if weap:
            extra.insert(0, weap)
        tail = f"  <i>{h(' '.join(extra))}</i>" if extra else ""
        return f"{icon} <b>{h(killer)}</b> → {h(victim)}{tail}"
    if typ in ("bomb",) or "plant" in (entry.get("text") or "").lower():
        text = entry.get("text") or ""
        if "defus" in text.lower():
            return f"🧰 {h(text)}"
        return f"💣 {h(text)}"
    if typ in _ROUND_BREAK and typ != "round_start":
        return f"🏁 {h(entry.get('text') or '回合结束')}"
    if typ == "round_start":
        return "▶️ 回合开始"
    if typ == "quit":
        return None
    text = entry.get("text") or ""
    if not text:
        return None
    return f"• {h(text)}"


def format_telegram(snap: dict, *, log_limit: int = 10) -> str:
    t1 = (snap.get("team1") or {}).get("name") or "?"
    t2 = (snap.get("team2") or {}).get("name") or "?"
    live = "🔴 <b>LIVE</b>" if snap.get("live") else "📊 <b>SCORE</b>"
    round_text = h(snap.get("roundText") or "")
    score = h(snap.get("scoreText") or f"{snap.get('ctScore')}-{snap.get('tScore')}")

    lines = [
        f"{live}  {h(t1)}  <code>{score}</code>  {h(t2)}",
    ]
    if round_text:
        lines.append(f"🗺️ {round_text}")

    banner = _streak_banner(snap.get("log") or [])
    if banner:
        lines.append(banner)

    lines.append("")
    for i, team in enumerate(snap.get("teams") or []):
        mark = "🔵" if i == 0 else "🟠"
        lines.append(f"{mark} <b>{h(team.get('name') or '?')}</b>")
        players = list(team.get("players") or [])
        players.sort(key=lambda p: (-int(p.get("kills") or 0), float(p.get("adr") or 0)))
        for p in players:
            adr = p.get("adr")
            adr_s = f"{adr:.0f}" if isinstance(adr, float) else str(adr)
            nick = h(p.get("nick") or "?")
            lines.append(
                f"<code>{p.get('kills'):>2}/{p.get('assists')}/{p.get('deaths'):<2}</code>  {nick}  <i>{adr_s}</i>"
            )
        lines.append("")

    lines.append("📟 <b>log</b>")
    n = 0
    for entry in snap.get("log") or []:
        line = _log_line(entry)
        if not line:
            continue
        lines.append(line)
        n += 1
        if n >= log_limit:
            break

    url = snap.get("url")
    if url:
        lines.append("")
        lines.append(h(url))
    lines.append("")
    lines.append("<i>/bump 顶到最新</i>")
    return "\n".join(lines).strip() + "\n"


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
        top = max(star_n(x) for x in matches)
        head = f"<b>{h(event)}</b>"
        if top:
            head += f"  {'⭐' * top}"
        lines = [head]
        for r in matches:
            n = star_n(r)
            live = "🔴" if r.get("live") == "1" else "▫️"
            t1 = h(r.get("team1") or r.get("title") or "?")
            t2 = h(r.get("team2") or "")
            vs = f"{t1}  —  {t2}" if t2 else t1
            mid = h(r.get("id") or "")
            star_s = "⭐" * n if n else "·"
            lines.append(f"{live}  <b>{vs}</b>")
            lines.append(f"{star_s}   <code>/watch {mid}</code>")
        blocks.append("\n".join(lines))
    hint = (
        "<i>/matches all 显示无星比赛</i>"
        if starred_only
        else "<i>/matches 只看有星赛事</i>"
    )
    blocks.append(hint)
    return "\n\n".join(blocks) + "\n"
