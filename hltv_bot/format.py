from __future__ import annotations

import re
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

_STREAK_PLAIN = {
    2: "2K",
    3: "3K",
    4: "4K",
    5: "ACE",
}

_LINK_LABEL = {
    "connecting": ("connecting", True),
    "connected": ("", False),
    "idle": ("", False),
    "reconnect": ("reconnecting", True),
    "disconnected": ("disconnected", True),
}


def h(text: object) -> str:
    return escape(str(text), quote=False)


_RICH_BLOCK_RE = re.compile(
    r"</?(h[1-6]|p|ul|ol|li|table|tr|td|th|hr|footer|details|blockquote|"
    r"pre|figure|tg-button-row|tg-button)\b",
    re.I,
)


def plain_to_rich(text: str) -> str:
    """Turn a notice (plain or classic HTML) into a rich-html document.

    Block-tagged HTML is returned as-is. Otherwise blank lines split
    paragraphs and single newlines become <br>.
    """
    s = (text or "").strip()
    if not s:
        return "<p></p>"
    if _RICH_BLOCK_RE.search(s):
        return s
    chunks = re.split(r"\n\s*\n", s)
    parts: list[str] = []
    for chunk in chunks:
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        parts.append("<p>" + chunk.replace("\n", "<br>") + "</p>")
    return "".join(parts) or "<p></p>"


def format_kv_table(title: str, rows: list[tuple[str, str]]) -> str:
    body = "".join(
        f"<tr><th>{h(k)}</th><td>{v}</td></tr>" for k, v in rows if k is not None
    )
    head = f"<h3>{h(title)}</h3>" if title else ""
    return f'{head}<table bordered striped compact>{body}</table>'


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


def _log_line(entry: dict, *, kill_n: int = 0, rich: bool = False) -> str | None:
    typ = entry.get("type")
    if typ == "kill":
        killer, victim = _killer_victim(entry)
        weap = _weapon_label(entry.get("weapon") or "")
        extra: list[str] = []
        if entry.get("headshot"):
            extra.append("<mark>HS</mark>" if rich else "HS")
        if kill_n >= 2:
            if rich:
                extra.append(f"<mark>{h(_STREAK_PLAIN.get(kill_n, f'{kill_n}K'))}</mark>")
            else:
                extra.append(_STREAK.get(kill_n, f"{kill_n}K"))
        if rich:
            bits = [f"<b>{h(killer)}</b> killed {h(victim)}"]
            if weap:
                bits.append(f"· {h(weap)}")
            if extra:
                bits.append(" ".join(extra))
            return " ".join(bits)
        icon = "🎯" if entry.get("headshot") else "💀"
        bits = [f"{icon} <b>{h(killer)}</b> killed {h(victim)}"]
        if weap:
            bits.append(f"with {h(weap)}")
        if extra:
            bits.append(f"({h(', '.join(extra))})")
        return " ".join(bits)
    if typ in ("bomb",) or "plant" in (entry.get("text") or "").lower():
        text = entry.get("text") or ""
        if "defus" in text.lower() or "拆" in text:
            return f"{'<b>' if rich else '🧰 '}{h(text)}{'</b>' if rich else ''}"
        return f"{'<b>' if rich else '💣 '}{h(text)}{'</b>' if rich else ''}"
    if typ in _ROUND_BREAK and typ != "round_start":
        body = h(entry.get("text") or "回合结束")
        return f"<b>{body}</b>" if rich else f"🏁 {body}"
    if typ == "round_start":
        return "<i>回合开始</i>" if rich else "▶️ 回合开始"
    if typ in {"quit", "suicide"}:
        return None
    text = entry.get("text") or ""
    if not text:
        return None
    return h(text) if rich else f"• {h(text)}"


def _map_and_round(snap: dict) -> tuple[str, str]:
    raw = str(snap.get("roundText") or "").strip()
    if " - " in raw:
        left, right = raw.split(" - ", 1)
        if left.strip().isdigit():
            return right.strip(), left.strip()
        if right.strip().isdigit():
            return left.strip(), right.strip()
        return raw, ""
    return raw, ""


def _sorted_players(team: dict) -> list[dict]:
    players = list(team.get("players") or [])[:5]
    players.sort(key=lambda p: (-int(p.get("kills") or 0), -float(p.get("adr") or 0)))
    return players


def _adr_s(adr: object) -> str:
    try:
        return f"{float(adr):.0f}"
    except (TypeError, ValueError):
        return str(adr or "0")


def _player_table(side: str, team: dict, score: object) -> str:
    name = h(team.get("name") or side)
    caption = f"{h(side)} · {name} · {h(score)}"
    rows = [
        "<tr>"
        "<th>Player</th>"
        "<th align=\"right\">K</th>"
        "<th align=\"right\">A</th>"
        "<th align=\"right\">D</th>"
        "<th align=\"right\">ADR</th>"
        "</tr>"
    ]
    players = _sorted_players(team)
    if not players:
        rows.append("<tr><td colspan=\"5\"><i>no players</i></td></tr>")
    for p in players:
        rows.append(
            "<tr>"
            f"<td>{h(p.get('nick') or '?')}</td>"
            f"<td align=\"right\">{int(p.get('kills') or 0)}</td>"
            f"<td align=\"right\">{int(p.get('assists') or 0)}</td>"
            f"<td align=\"right\">{int(p.get('deaths') or 0)}</td>"
            f"<td align=\"right\">{h(_adr_s(p.get('adr')))}</td>"
            "</tr>"
        )
    return (
        '<table bordered striped compact>'
        f"<caption>{caption}</caption>"
        + "".join(rows)
        + "</table>"
    )


def _log_items(log: list[dict], *, rich: bool, limit: int) -> list[str]:
    kill_ns = round_kill_counts(log)
    out: list[str] = []
    for entry in log:
        line = _log_line(entry, kill_n=kill_ns.get(id(entry), 0), rich=rich)
        if not line:
            continue
        out.append(line)
        if len(out) >= limit:
            break
    return out


def format_connecting_html(
    *,
    team1: str = "?",
    team2: str = "?",
    list_id: str = "",
    url: str | None = None,
    link: str = "connecting",
) -> str:
    status, hot = _LINK_LABEL.get(link, (link, True))
    status_html = f"<mark>{h(status)}</mark>" if status else ""
    title = "LIVE"
    if url:
        title = f'<a href="{h(url)}">LIVE</a>'
    parts = [
        f"<h3>{title}</h3>",
        f"<p><b>{h(team1)}</b> vs <b>{h(team2)}</b></p>",
    ]
    meta_bits = [status_html]
    if list_id:
        meta_bits.append(f"<code>{h(list_id)}</code>")
    meta_bits = [x for x in meta_bits if x]
    if meta_bits:
        parts.append("<p>" + " · ".join(meta_bits) + "</p>")
    parts.append("<footer>/bump</footer>")
    return "".join(parts)


def _plain(name: object, width: int) -> str:
    s = str(name or "?").replace("<", "").replace(">", "")[:width]
    return s + " " * (width - len(s))


def _mono(nick: str, k, a, d, adr, width: int = 12) -> str:
    n = str(nick).replace("<", "").replace(">", "")[:width]
    n = n + " " * (width - len(n))
    try:
        adr_s = f"{float(adr):.0f}"
    except (TypeError, ValueError):
        adr_s = str(adr)
    return f"{n} {int(k or 0):>2} {int(a or 0):>2} {int(d or 0):>2} {adr_s:>4}"


def format_rich_html(snap: dict, *, log_limit: int = 15) -> str:
    """HLTV-style scoreboard as Telegram rich HTML (Bot API 10.3 tags)."""
    teams = list(snap.get("teams") or [])
    ct_team = teams[0] if teams else {"name": (snap.get("team2") or {}).get("name") or "CT", "players": []}
    t_team = teams[1] if len(teams) > 1 else {"name": (snap.get("team1") or {}).get("name") or "T", "players": []}
    ct = snap.get("ctScore")
    t = snap.get("tScore")
    if ct is None or t is None:
        parts = str(snap.get("scoreText") or "0-0").replace(":", "-").split("-")
        ct, t = (parts + ["0", "0"])[:2]
    map_name, round_n = _map_and_round(snap)
    status, hot = _LINK_LABEL.get(str(snap.get("link") or "connected"), ("", False))
    url = snap.get("url") or ""
    live_label = "LIVE" if snap.get("live") else "SCORE"
    if url:
        live_label = f'<a href="{h(url)}">{live_label}</a>'
    title_bits = [live_label]
    if map_name:
        title_bits.append(h(map_name))
    heading = " · ".join(title_bits)

    score_line = (
        f"<b>{h(ct_team.get('name'))}</b> <code>{h(ct)}</code>"
        " &ndash; "
        f"<code>{h(t)}</code> <b>{h(t_team.get('name'))}</b>"
    )
    sub: list[str] = []
    if round_n:
        sub.append(f"<i>R{h(round_n)}</i>")
    if status:
        sub.append(f"<mark>{h(status)}</mark>" if hot else f"<i>{h(status)}</i>")
    sub_html = f"<br>{' · '.join(sub)}" if sub else ""

    visible = max(6, min(10, log_limit))
    lines = _log_items(snap.get("log") or [], rich=True, limit=log_limit)
    head, tail = lines[:visible], lines[visible:]
    if head:
        log_html = "<ul>" + "".join(f"<li>{x}</li>" for x in head) + "</ul>"
        if tail:
            log_html += (
                "<details><summary>Earlier</summary>"
                "<ul>" + "".join(f"<li>{x}</li>" for x in tail) + "</ul>"
                "</details>"
            )
    else:
        log_html = "<p><i>no events</i></p>"

    blocks = [
        f"<h3>{heading}</h3>",
        f"<p>{score_line}{sub_html}</p>",
        _player_table("CT", ct_team, ct),
        _player_table("T", t_team, t),
        "<h4>Game log</h4>",
        log_html,
        "<footer>/bump</footer>",
    ]
    if url:
        blocks.append(
            "<tg-button-row>"
            f'<tg-button type="url" url="{h(url)}">HLTV</tg-button>'
            "</tg-button-row>"
        )
    return "".join(blocks)


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
    link = {
        "connecting": "🟡 连接中",
        "connected": "🟢 正常",
        "idle": "🟢 正常",
        "reconnect": "🟠 重连",
        "disconnected": "🔴 断开",
    }.get(str(snap.get("link") or "connected"), "🟢 正常")

    title = f"{live}  <b>{h(round_text)}</b>" if round_text else live
    score_line = (
        f"<b>{h(left.get('name'))}</b> <code>{ct}</code>"
        f"    "
        f"<b>{h(right.get('name'))}</b> <code>{t}</code>"
    )
    lines = [
        f"{title}  ·  {link}",
        score_line,
    ]

    lines.append(_HR)
    for side, team in (("CT", left), ("T", right)):
        players = _sorted_players(team)
        lines.append(f"<b>{h(side)} {h(team.get('name'))}</b>")
        if players:
            body = "\n".join(
                _mono(p.get("nick") or "?", p.get("kills"), p.get("assists"), p.get("deaths"), p.get("adr"))
                for p in players
            )
            lines.append(f"<pre>             K  A  D  ADR\n{body}</pre>")
        else:
            lines.append("<i>no players</i>")

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


def format_match_list_rich(
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
            return (
                "<h3>Matches</h3>"
                "<p>没有带星级的比赛。</p>"
                "<p>发 <code>/matches all</code> 查看全部。</p>"
            )
        return "<h3>Matches</h3><p>今天没有抓到比赛。</p>"

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

    parts = ["<h3>Matches</h3>"]
    for event, matches in sorted(grouped.items(), key=event_key):
        matches = sorted(matches, key=match_key)
        rows_html = [
            "<tr>"
            "<th></th>"
            "<th>Match</th>"
            "<th align=\"right\">Time</th>"
            "</tr>"
        ]
        for r in matches:
            live = r.get("live") == "1"
            clock = r.get("time") or ("LIVE" if live else "")
            t1 = h(r.get("team1") or r.get("title") or "?")
            t2 = h(r.get("team2") or "")
            vs = f"<b>{t1}</b> – {t2}" if t2 else f"<b>{t1}</b>"
            mid = h(r.get("id") or "")
            n = star_n(r)
            stars = "⭐" * n if n else ""
            status = "<mark>LIVE</mark>" if live else stars
            time_cell = h(clock) if clock and not live else (stars if live and stars else "")
            rows_html.append(
                "<tr>"
                f"<td>{status}</td>"
                f"<td>{vs}<br>/watch {mid}</td>"
                f"<td align=\"right\"><code>{time_cell}</code></td>"
                "</tr>"
            )
        parts.append(f"<h4>{h(event)}</h4>")
        parts.append(
            '<table bordered striped compact>'
            + "".join(rows_html)
            + "</table>"
        )
    hint = (
        "时间 UTC+8 · /matches all 显示无星比赛"
        if starred_only
        else "时间 UTC+8 · /matches 只看有星赛事"
    )
    parts.append(f"<footer>{h(hint)}</footer>")
    return "".join(parts)
