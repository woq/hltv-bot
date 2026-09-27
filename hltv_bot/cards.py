"""HTML cards rendered to PNG. Telegram gets the picture plus a short caption."""

from __future__ import annotations

import io
from html import escape

_BG = (18, 17, 14)

_CSS = """
@page { size: PAGEWpx PAGEHpx; margin: 0; }
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: #12110e;
  color: #f3ecdf;
  font-family: "WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans", sans-serif;
}
.card { width: PAGEWpx; padding: 28px 26px 22px; }
.kicker {
  font-size: 13px;
  letter-spacing: 0.34em;
  color: #a39886;
}
.kicker em { font-style: normal; color: #e6ff4d; letter-spacing: 0.18em; }
.trow { display: flex; align-items: center; margin-top: 14px; }
.tlogo, .tlogo-ph { width: 28px; height: 28px; margin-right: 12px; object-fit: contain; flex: 0 0 28px; }
.tlogo-ph, .elogo-ph { display: inline-block; background: #2a261f; }
.name {
  flex: 1;
  font-size: 28px;
  line-height: 1;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.sc {
  width: 52px;
  text-align: right;
  font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
  font-size: 36px;
  line-height: 1;
  color: #e6ff4d;
}
.sc.live { color: #ff5a3c; }
.sc.final { color: #f3ecdf; }
.sc.soon { color: #5c564c; }
.elogo { height: 16px; width: auto; max-width: 48px; object-fit: contain; margin-right: 8px; vertical-align: middle; }
.elogo-ph { display: none; }
.eventline { display: flex; align-items: center; }
.rule { height: 1px; background: #2c2822; margin: 22px 0 16px; }
.event { font-size: 16px; color: #d9cbb6; }
.note {
  margin-top: 12px;
  font-size: 15px;
  letter-spacing: 0.08em;
  color: #e6ff4d;
}
.g-title { font-size: 22px; font-weight: 700; letter-spacing: 0.04em; }
.g-sub { margin-top: 6px; color: #a39886; font-size: 13px; }
.g-block { margin-top: 16px; }
.g-k { color: #e6ff4d; font-size: 13px; letter-spacing: 0.16em; }
.g-line { margin-top: 4px; font-size: 15px; line-height: 1.45; color: #f3ecdf; }
.when {
  margin-top: 8px;
  font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
  font-size: 15px;
  letter-spacing: 0.06em;
  color: #a39886;
}
.streak { margin-top: 16px; font-size: 18px; color: #e6ff4d; }
.place { margin-top: 10px; font-size: 16px; color: #d9cbb6; }
.flag { font-family: "Noto Color Emoji", "DejaVu Sans", sans-serif; }
.remain { margin-top: 14px; font-size: 22px; }
.sheet-title { font-size: 12px; letter-spacing: 0.22em; color: #a39886; }
.mcard {
  margin-top: 14px;
  padding: 12px 12px 11px;
  background: #221f1a;
  border-radius: 12px;
}
.mhead { display: flex; align-items: center; }
.mtag {
  width: 38px;
  font-size: 9px;
  letter-spacing: 0.06em;
  color: transparent;
  font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
}
.mtag.on { color: #ff5a3c; }
.mtime {
  flex: 1;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #a39886;
  font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
}
.mstars { color: #e6ff4d; font-size: 12px; letter-spacing: 0.12em; }
.mmap {
  margin-top: 8px;
  font-size: 13px;
  letter-spacing: 0.03em;
}
.mmap-now { color: #e6ff4d; font-weight: 700; }
.mmap-rest { color: #8d8478; }
.mmap-rest::before { content: " · "; color: #5c564c; }
.mmap-fmt { color: #5c564c; }
.mmap-fmt::before { content: " · "; }
table.sheet { width: 100%; border-collapse: collapse; }
td.slot {
  width: 36px;
  padding: 12px 0 0;
  vertical-align: top;
  border-top: 1px solid #2c2822;
}
td.slot div {
  width: 36px;
  font-size: 9px;
  letter-spacing: 0.04em;
  color: #ff5a3c;
  font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
}
td.slot.off div { color: #12110e; }
td.body { padding: 8px 0 8px; border-top: 1px solid #2c2822; }
.mbody .trow { margin-top: 4px; }
.mbody .name { font-size: 15px; }
.mbody .sc { width: 28px; font-size: 16px; }
.mbody .tlogo, .mbody .tlogo-ph { width: 22px; height: 22px; flex-basis: 22px; margin-right: 8px; }
.tlogo svg, .mbody .tlogo svg { width: 100%; height: 100%; display: block; }
.sub {
  display: flex;
  align-items: center;
  margin-top: 4px;
  font-size: 11px;
  color: #a39886;
}
.event-card { position: relative; }
.event-bg {
  position: absolute;
  right: 0; top: 0; bottom: 0;
  width: 58%;
  background-repeat: no-repeat;
  background-position: right center;
  background-size: contain;
  opacity: 0.55;
}
.event-shade {
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, #12110e 42%, rgba(18,17,14,0.35) 100%);
}
.event-copy { position: relative; }
"""


def _e(value: object) -> str:
    return escape(str(value or ""))


_CARD_W = 520
_LIST_W = 416  # list cards are 20% narrower for a phone
# List name column is the gap between the 22px logo and the score on a 416px card.
# At 15px that is 22 Latin letters. The 520px match card uses 28px type, so 16.
# A CJK character counts as two letters.
LIST_NAME_UNITS = 22
CARD_NAME_UNITS = 16


def _team_logo_uri(team_id: str, url: str) -> str:
    team_id = str(team_id or "").strip()
    if team_id.isdigit():
        try:
            from hltv_bot.team_logos import team_logo_uri

            found = team_logo_uri(team_id, url)
            if found:
                return found
        except Exception:
            pass
    return _logo_uri(url)


def _logo_uri(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("data:image"):
        return url
    try:
        from hltv_bot.team_logos import cached_data_uri, ensure_team_logos

        ensure_team_logos([url])
        return cached_data_uri(url) or ""
    except Exception:
        return ""


def _event_logo_uri(event_id: str, url: str, size: str = "s") -> str:
    url = (url or "").strip()
    event_id = str(event_id or "").strip()
    if url.startswith("data:image"):
        return url
    if event_id:
        try:
            from hltv_bot.events import ensure_event_logos, get_cached_logo_data_uri

            ensure_event_logos([(event_id, url)], size=size)
            found = get_cached_logo_data_uri(event_id, size=size)
            if found:
                return found
            if size == "s":
                found = get_cached_logo_data_uri(event_id, size="l")
                if found:
                    return found
        except Exception:
            return ""
    return ""


def render_card(card: dict) -> bytes:
    view = card.get("view") or "match"
    if view == "matches":
        height = 48 + 168 * max(1, min(len(card.get("rows") or []), 12))
        html = _matches_html(card, height, _LIST_W)
    elif view == "events":
        height = 118 + 88 * max(1, min(len(card.get("rows") or []), 8))
        html = _events_html(card, height, _LIST_W)
    elif view == "event":
        html = _event_html(card, 420, _CARD_W)
    elif view == "guide":
        html = _guide_html(card, 760, _CARD_W)
    else:
        height = 420 if card.get("note") else 380
        html = _match_html(card, height, _CARD_W)
    return _png(html)


def _png(html: str) -> bytes:
    import weasyprint
    import pypdfium2
    from PIL import Image, ImageChops

    pdf = weasyprint.HTML(string=html).write_pdf()
    doc = pypdfium2.PdfDocument(pdf)
    image = doc[0].render(scale=2).to_pil().convert("RGB")
    bg = Image.new("RGB", image.size, _BG)
    diff = ImageChops.difference(image, bg)
    box = diff.getbbox()
    if box:
        image = image.crop((0, 0, image.width, min(image.height, box[3] + 28)))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _page(body: str, height: int, width: int) -> str:
    css = _CSS.replace("PAGEW", str(width)).replace("PAGEH", str(height))
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + css
        + "</style></head><body><div class='card'>"
        + body
        + "</div></body></html>"
    )


def _img(uri: str, cls: str) -> str:
    if uri.startswith("data:image/svg"):
        svg = _svg_markup(uri)
        if svg:
            return f'<span class="{cls}">{svg}</span>'
    if uri.startswith("data:image"):
        return f'<img class="{cls}" src="{uri}" />'
    return f'<span class="{cls}-ph"></span>'


def _svg_markup(uri: str) -> str:
    import base64
    import re

    raw = uri.split(",", 1)
    if len(raw) != 2:
        return ""
    try:
        text = base64.b64decode(raw[1]).decode("utf-8", "replace")
    except Exception:
        return ""
    start = text.lower().find("<svg")
    if start < 0:
        return ""
    svg = text[start:]
    if "class=" in svg[:80].lower():
        return svg
    return re.sub(r"<svg\b", "<svg class='logo-svg'", svg, count=1, flags=re.I)


def _team_row(
    name: str,
    score: str,
    logo: str,
    accent: str,
    *,
    team_id: str = "",
    limit: int = CARD_NAME_UNITS,
) -> str:
    from hltv_bot.matches import short_team

    mark = _e(score) if score else "–"
    return (
        "<div class='trow'>"
        + _img(_team_logo_uri(team_id, logo), "tlogo")
        + f"<div class='name'>{_e(short_team(name, limit))}</div>"
        + f"<div class='sc {accent}'>{mark}</div>"
        + "</div>"
    )


def _match_html(card: dict, height: int, width: int) -> str:
    kind = card.get("kind") or "score"
    accent = {"preview": "live", "final": "final", "soon": "soon"}.get(kind, "")
    pair = card.get("pair") or ("", "")
    left = pair[0] if pair and pair[0] else ""
    right = pair[1] if pair and len(pair) > 1 else ""
    bits = [
        f"<div class='kicker'>{_e(card.get('label'))}</div>",
        _team_row(card.get("team1") or "?", left, card.get("logo1") or "", accent, team_id=str(card.get("team1_id") or "")),
        _team_row(card.get("team2") or "?", right, card.get("logo2") or "", accent, team_id=str(card.get("team2_id") or "")),
        "<div class='rule'></div>",
        "<div class='eventline'>"
        + _img(_event_logo_uri(str(card.get("event_id") or ""), str(card.get("event_logo") or ""), "s"), "elogo")
        + f"<div class='event'>{_e(card.get('event'))}</div></div>",
    ]
    if card.get("note"):
        bits.append(f"<div class='note'>{_e(card.get('note'))}</div>")
    if card.get("clock"):
        bits.append(f"<div class='when'>{_e(card.get('clock'))}   UTC+8</div>")
    return _page("".join(bits), height, width)


def _event_html(card: dict, height: int, width: int) -> str:
    logo = _event_logo_uri(
        str(card.get("id") or ""),
        str(card.get("logo_small_url") or card.get("logo_url") or ""),
        "s",
    )
    bits = [
        "<div class='event-card'>",
        "<div class='event-copy'>",
        "<div class='eventline'>"
        + _img(logo, "elogo")
        + f"<div class='kicker'>赛事  ·  {_e(card.get('tier'))}</div></div>",
        f"<div class='name' style='margin-top:22px'>{_e(card.get('name'))}</div>",
    ]
    place = " ".join(x for x in (card.get("flag") or "", card.get("location") or "") if x)
    if place:
        bits.append(f"<div class='place'><span class='flag'>{card.get('flag') or ''}</span> {_e(card.get('location'))}</div>")
    bits.append("<div class='rule'></div>")
    if card.get("clock"):
        bits.append(f"<div class='when'>{_e(card.get('clock'))}   UTC+8</div>")
    bits.append(f"<div class='remain'>{_e(card.get('remain'))}</div>")
    bits.append("</div></div>")
    return _page("".join(bits), height, width)


def _guide_html(card: dict, height: int, width: int) -> str:
    morning = int(card.get("morning") or 10)
    evening = int(card.get("evening") or 20)
    lines = [
        ("默认", "至少 1 星，并且赛事名是 Major / T1。"),
        ("比分", "只在有直播时刷新赛程页。进入 Live 的 0:0 只预告一次。"),
        ("BO", "BO1 就是这场比分。BO3 / BO5 标成当前图。"),
        ("比赛日", f"UTC+8 {morning:02d}:00 到次日 {morning:02d}:00，含国外晚上打到凌晨的比赛。"),
        ("赛程", f"每天 {morning:02d}:00 发整日，{evening:02d}:00 发还没开的，含次日凌晨。"),
        ("补充", "/follow 单场。/cover 整赛事，每个比赛日都算。/ignore 摘掉一场。"),
        ("开关", "/watch 管比分。/track 管每天两次的赛程。两套互不影响。"),
    ]
    bits = [
        "<div class='g-title'>hltv-bot</div>",
        "<div class='g-sub'>时间一律 UTC+8 · 提醒默认无声</div>",
    ]
    for title, body in lines:
        bits.append(
            "<div class='g-block'>"
            f"<div class='g-k'>{_e(title)}</div>"
            f"<div class='g-line'>{_e(body)}</div>"
            "</div>"
        )
    return _page("".join(bits), height, width)


def _map_line(row: dict) -> str:
    from hltv_bot.matches import map_order

    current, rest = map_order(row)
    fmt = (row.get("format") or "").strip().lower()
    if not current and not rest and not fmt:
        return ""
    bits = ["<div class='mmap'>"]
    if current:
        bits.append(f"<span class='mmap-now'>{_e(current)}</span>")
    for name in rest:
        bits.append(f"<span class='mmap-rest'>{_e(name)}</span>")
    if fmt:
        bits.append(f"<span class='mmap-fmt'>{_e(fmt)}</span>")
    bits.append("</div>")
    return "".join(bits)


def _matches_html(card: dict, height: int, width: int) -> str:
    rows = list(card.get("rows") or [])[:12]
    bits = [f"<div class='sheet-title'>{_e(card.get('title') or '比赛  ·  UTC+8')}</div>"]
    for row in rows:
        live = row.get("live") == "1"
        a = (row.get("score1") or "").strip()
        b = (row.get("score2") or "").strip()
        clock = (row.get("time") or "").strip()
        if live and clock.upper() == "LIVE":
            clock = ""
        stars = "★" * _stars(row)
        sc_accent = "live" if live else ("final" if (a or b) else "soon")
        mid = str(row.get("id") or "").strip()
        event = (row.get("event") or "").strip()
        foot = "  ·  ".join(x for x in (event, f"#{mid}" if mid else "") if x)
        bits.append(
            "<div class='mcard mbody'>"
            "<div class='mhead'>"
            f"<span class='mtag{' on' if live else ''}'>LIVE</span>"
            f"<span class='mtime'>{_e(clock)}</span>"
            f"<span class='mstars'>{_e(stars)}</span>"
            "</div>"
            + _team_row(
                row.get("team1") or "?",
                a,
                row.get("team1_logo") or "",
                sc_accent,
                team_id=str(row.get("team1_id") or ""),
                limit=LIST_NAME_UNITS,
            )
            + _team_row(
                row.get("team2") or "?",
                b,
                row.get("team2_logo") or "",
                sc_accent,
                team_id=str(row.get("team2_id") or ""),
                limit=LIST_NAME_UNITS,
            )
            + "<div class='sub'>"
            + _img(_event_logo_uri(str(row.get("event_id") or ""), str(row.get("event_logo") or ""), "s"), "elogo")
            + f"{_e(foot)}</div>"
            + _map_line(row)
            + "</div>"
        )
    if not rows:
        bits.append("<div class='mcard mbody'>没有比赛</div>")
    return _page("".join(bits), height, width)


def _events_html(card: dict, height: int, width: int) -> str:
    rows = list(card.get("rows") or [])[:8]
    bits = ["<div class='sheet-title'>赛事  ·  Major / T1</div>"]
    for ev in rows:
        logo = _event_logo_uri(str(ev.get("id") or ""), str(ev.get("logo_url") or ""), "l")
        bg = ""
        if logo.startswith("data:image"):
            bg = f"<div class='event-bg' style=\"background-image:url('{logo}')\"></div><div class='event-shade'></div>"
        place = " ".join(x for x in (ev.get("flag") or "", ev.get("location") or "") if x)
        sub_items = [ev.get("tier"), place, ev.get("when"), ev.get("prize")]
        sub_str = "  ·  ".join(_e(x) for x in sub_items if x)
        bits.append(
            "<div class='event-card' style='margin-top:10px;padding-top:8px;border-top:1px solid #2c2822'>"
            + bg
            + "<div class='event-copy'>"
            + f"<div class='name' style='font-size:16px'>{_e(ev.get('name'))}</div>"
            + f"<div class='sub'>{sub_str}</div>"
            + "</div></div>"
        )
    if not rows:
        bits.append("<div class='sub'>没有赛事</div>")
    return _page("".join(bits), height, width)


def _stars(row: dict) -> int:
    try:
        return max(0, min(5, int(row.get("stars") or 0)))
    except (TypeError, ValueError):
        return 0
