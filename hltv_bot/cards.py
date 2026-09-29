"""HTML cards rendered to PNG. Telegram gets the picture plus a short caption."""

from __future__ import annotations

import io
from html import escape
from pathlib import Path

_BG = (20, 19, 17)

_CSS = """
@page { size: PAGEWpx PAGEHpx; margin: 0; }
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0;
  background: #141311;
  color: #f6f3ee;
  font-family: "Rajdhani", "WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans", sans-serif;
  text-rendering: geometricPrecision;
}
.card { position: relative; width: PAGEWpx; padding: 28px 26px 42px; }
.stamp {
  position: absolute;
  right: 22px;
  bottom: 14px;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
  font-size: 14px;
  letter-spacing: 0.04em;
  color: #d2ccc2;
  font-weight: 600;
}
.kicker {
  font-size: 13px;
  letter-spacing: 0.34em;
  color: #e4ddd2;
  font-weight: 600;
}
.kicker em { font-style: normal; color: #e8ff5a; letter-spacing: 0.18em; }
.trow { display: flex; align-items: center; margin-top: 14px; }
.tlogo, .tlogo-ph { width: 28px; height: 28px; margin-right: 12px; object-fit: contain; flex: 0 0 28px; }
.tlogo-ph, .elogo-ph { display: inline-block; background: #3a3833; }
.name {
  flex: 1;
  min-width: 0;
  font-size: 28px;
  line-height: 1;
  font-weight: 700;
  color: #f6f3ee;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hero { margin-top: 18px; display: flex; align-items: center; }
.hero .name { font-size: 34px; }
.hero-score {
  margin-top: 10px;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
  font-size: 42px;
  line-height: 1;
  letter-spacing: 0.06em;
  font-weight: 700;
}
.hero-score .num { color: #f6f3ee; }
.hero-score .dash { color: #9a948a; padding: 0 10px; }
.opp { margin-top: 8px; font-size: 16px; color: #e4ddd2; font-weight: 600; }
.mapline { margin-top: 14px; }
.mp {
  display: inline-flex;
  align-items: center;
  margin-right: 14px;
  font-size: 15px;
  font-weight: 600;
  color: #9a948a;
}
.mp.won { color: #f6f3ee; }
.mp.now { color: #e8ff5a; }
.mplogo, .mplogo-ph { width: 16px; height: 16px; margin-left: 6px; object-fit: contain; }
.mplogo-ph { display: none; }
.sc {
  width: 52px;
  text-align: right;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
  font-size: 36px;
  line-height: 1;
  color: #e8ff5a;
}
.sc.live { color: #ff6a45; }
.sc.final { color: #f6f3ee; }
.sc.soon { color: #d2ccc2; }
.elogo { height: 16px; width: auto; max-width: 48px; object-fit: contain; margin-right: 8px; vertical-align: middle; }
.elogo-ph { display: none; }
.eventline { display: flex; align-items: center; }
.rule { height: 1px; background: #4a463f; margin: 22px 0 16px; }
.event { font-size: 16px; color: #e4ddd2; font-weight: 600; }
.note {
  margin-top: 12px;
  font-size: 15px;
  letter-spacing: 0.08em;
  color: #e8ff5a;
  font-weight: 600;
}
.g-title { font-size: 22px; font-weight: 700; letter-spacing: 0.04em; color: #f6f3ee; }
.g-sub { margin-top: 6px; color: #e4ddd2; font-size: 14px; font-weight: 600; }
.g-block { margin-top: 16px; }
.g-k { color: #e8ff5a; font-size: 13px; letter-spacing: 0.16em; font-weight: 700; }
.g-line { margin-top: 4px; font-size: 16px; line-height: 1.45; color: #f6f3ee; font-weight: 600; }
.when {
  margin-top: 8px;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
  font-size: 16px;
  letter-spacing: 0.04em;
  color: #e4ddd2;
  font-weight: 600;
}
.streak { margin-top: 16px; font-size: 18px; color: #e8ff5a; font-weight: 700; }
.place { margin-top: 10px; font-size: 16px; color: #e4ddd2; font-weight: 600; }
.flag { font-family: "Noto Color Emoji", "DejaVu Sans", sans-serif; }
.remain { margin-top: 14px; font-size: 22px; }
.sheet-title { font-size: 14px; letter-spacing: 0.16em; color: #e4ddd2; font-weight: 700; }
.mcard {
  margin-top: 14px;
  padding: 12px 12px 12px;
  background: #32302b;
  border-radius: 12px;
}
.mhead { display: flex; align-items: center; }
.mtag {
  width: 38px;
  font-size: 9px;
  letter-spacing: 0.06em;
  color: transparent;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
}
.mtag.on { color: #ff6a45; font-weight: 700; }
.mtime {
  flex: 1;
  font-size: 14px;
  letter-spacing: 0.02em;
  color: #e4ddd2;
  font-weight: 600;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
}
.mstars { color: #e8ff5a; font-size: 14px; letter-spacing: 0.08em; }
.mmap {
  margin-top: 8px;
  font-size: 15px;
  letter-spacing: 0.02em;
}
.mmap-now { color: #e8ff5a; font-weight: 700; }
.mmap-rest { color: #e4ddd2; font-weight: 600; }
.mmap-fmt { color: #d2ccc2; font-weight: 600; }
.mmap-sep { color: #9a948a; font-weight: 600; }
table.sheet { width: 100%; border-collapse: collapse; }
td.slot {
  width: 36px;
  padding: 12px 0 0;
  vertical-align: top;
  border-top: 1px solid #4a463f;
}
td.slot div {
  width: 36px;
  font-size: 9px;
  letter-spacing: 0.04em;
  color: #ff6a45;
  font-family: "Rajdhani", "Liberation Sans", "DejaVu Sans", sans-serif;
}
td.slot.off div { color: #141311; }
td.body { padding: 8px 0 8px; border-top: 1px solid #4a463f; }
.mbody .trow { margin-top: 4px; }
.mbody .name { font-size: 15px; }
.mbody .sc { width: 28px; font-size: 16px; }
.mbody .tlogo, .mbody .tlogo-ph { width: 22px; height: 22px; flex-basis: 22px; margin-right: 8px; }
.tlogo svg, .mbody .tlogo svg { width: 100%; height: 100%; display: block; }
.sub {
  display: flex;
  align-items: center;
  margin-top: 6px;
  font-size: 14px;
  color: #e4ddd2;
  font-weight: 600;
}
.event-card { position: relative; overflow: hidden; }
.event-bg {
  position: absolute;
  background-repeat: no-repeat;
  background-position: center;
  background-size: contain;
}
.event-shade { position: absolute; inset: 0; }
.event-copy { position: relative; }
.event-solo { min-height: 188px; }
.event-solo .event-bg { width: 176px; height: 176px; right: 4px; top: 18px; }
.event-solo .event-shade {
  background: linear-gradient(90deg, #141311 0%, #141311 48%, rgba(20,19,17,0) 64%);
}
.event-solo .event-copy { padding-right: 156px; min-height: 176px; }
.event-solo .name { margin-top: 14px; font-size: 26px; line-height: 1.12; white-space: normal; }
.event-row { min-height: 112px; margin-top: 14px; padding-top: 10px; border-top: 1px solid #4a463f; }
.event-row .event-bg { width: 92px; height: 92px; right: 0; top: 14px; }
.event-row .event-shade {
  background: linear-gradient(90deg, #141311 0%, #141311 52%, rgba(20,19,17,0) 74%);
}
.event-row .event-copy { padding-right: 100px; }
.event-row .name { margin-top: 4px; font-size: 18px; line-height: 1.15; white-space: normal; }
.event-chip { min-height: 76px; margin-top: 10px; }
.event-chip .event-bg { width: 72px; height: 72px; right: 0; top: 2px; }
.event-chip .event-shade {
  background: linear-gradient(90deg, #141311 0%, #141311 56%, rgba(20,19,17,0) 78%);
}
.mcard .event-chip .event-shade {
  background: linear-gradient(90deg, #32302b 0%, #32302b 56%, rgba(50,48,43,0) 78%);
}
.event-chip .event-copy { padding-right: 80px; }
.event-chip .name { margin-top: 2px; font-size: 16px; line-height: 1.15; white-space: normal; }
.event-chip .tier { margin-top: 0; }
.event-copy.tier-major .name,
.event-copy.tier-major .place,
.event-copy.tier-major .when,
.event-copy.tier-major .prize,
.event-copy.tier-major .sub,
.event-copy.tier-major .remain { color: #ffc14a; }
.event-copy.tier-t1 .name,
.event-copy.tier-t1 .place,
.event-copy.tier-t1 .when,
.event-copy.tier-t1 .prize,
.event-copy.tier-t1 .sub,
.event-copy.tier-t1 .remain { color: #e8ff5a; }
.event-copy.tier-t2 .name,
.event-copy.tier-t2 .place,
.event-copy.tier-t2 .when,
.event-copy.tier-t2 .prize,
.event-copy.tier-t2 .sub,
.event-copy.tier-t2 .remain { color: #7eb8ff; }
.event-copy.tier-t3 .name,
.event-copy.tier-t3 .place,
.event-copy.tier-t3 .when,
.event-copy.tier-t3 .prize,
.event-copy.tier-t3 .sub,
.event-copy.tier-t3 .remain { color: #e0a36a; }
.event-copy.tier-other .name,
.event-copy.tier-other .place,
.event-copy.tier-other .when,
.event-copy.tier-other .prize,
.event-copy.tier-other .sub,
.event-copy.tier-other .remain { color: #d2ccc2; }
.tier {
  display: inline-block;
  margin-top: 10px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.16em;
}
.tier.tier-major {
  color: #ffc14a;
  letter-spacing: 0.14em;
  font-size: 15px;
  border-bottom: 2px solid #ffc14a;
  padding-bottom: 1px;
}
.tier-t1 { color: #e8ff5a; }
.tier-t2 { color: #7eb8ff; }
.tier-t3 { color: #e0a36a; }
.tier-other { color: #9a948a; }
.remain.final { margin-top: 16px; font-size: 14px; letter-spacing: 0.16em; color: #ff6a45; }
.prize { margin-top: 4px; font-size: 14px; color: #e4ddd2; font-weight: 600; }
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
        height = 56 + 220 * max(1, min(len(card.get("rows") or []), 12))
        html = _matches_html(card, height, _LIST_W)
    elif view == "events":
        height = 64 + 132 * max(1, min(len(card.get("rows") or []), 8))
        html = _events_html(card, height, _LIST_W)
    elif view == "event":
        html = _event_html(card, 420, _CARD_W)
    elif view == "guide":
        html = _guide_html(card, 760, _CARD_W)
    else:
        height = 560 if card.get("kind") in {"map", "match"} else (500 if card.get("map_rows") else 460)
        html = _match_html(card, height, _CARD_W)
    return _png(html)


def _png(html: str) -> bytes:
    import weasyprint
    import pypdfium2
    from PIL import Image, ImageChops

    # CSS pixels are 96 per inch; PDF points are 72. scale=4 is 3 device
    # pixels per CSS pixel, so phone screens are not enlarging a soft image.
    pdf = weasyprint.HTML(string=html).write_pdf()
    doc = pypdfium2.PdfDocument(pdf)
    image = doc[0].render(scale=4).to_pil().convert("RGB")
    bg = Image.new("RGB", image.size, _BG)
    diff = ImageChops.difference(image, bg)
    box = diff.getbbox()
    if box:
        image = image.crop((0, 0, image.width, min(image.height, box[3] + 28)))
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _font_css() -> str:
    directory = Path(__file__).resolve().parent / "fonts"
    faces = []
    for weight, filename in (
        (400, "Rajdhani-Regular.ttf"),
        (500, "Rajdhani-Medium.ttf"),
        (600, "Rajdhani-SemiBold.ttf"),
        (700, "Rajdhani-Bold.ttf"),
    ):
        uri = (directory / filename).as_uri()
        faces.append(
            "@font-face{"
            "font-family:'Rajdhani';"
            f"src:url('{uri}');"
            f"font-weight:{weight};font-style:normal;"
            "}"
        )
    return "".join(faces)


def _page(body: str, height: int, width: int) -> str:
    from datetime import datetime, timedelta, timezone

    css = _font_css() + _CSS.replace("PAGEW", str(width)).replace("PAGEH", str(height))
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M:%S")
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        + css
        + "</style></head><body><div class='card'>"
        + body
        + f"<div class='stamp'>{_e(stamp)} UTC+8</div>"
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


def _map_strip(rows: list) -> str:
    if not rows:
        return ""
    bits = []
    for item in rows:
        name = _e(item.get("name") or "")
        cls = "mp"
        if item.get("winner"):
            cls += " won"
        if item.get("current"):
            cls += " now"
        logo = ""
        if item.get("winner"):
            logo = _img(_team_logo_uri(str(item.get("team_id") or ""), str(item.get("logo") or "")), "mplogo")
        bits.append(f"<span class='{cls}'>{name}{logo}</span>")
    return f"<div class='mapline'>{''.join(bits)}</div>"


def _winner_block(card: dict) -> str:
    pair = card.get("pair") or ("", "")
    left = str(pair[0] if pair else "")
    right = str(pair[1] if len(pair) > 1 else "")
    bits = [f"<div class='kicker'>{_e(card.get('label'))}</div>"]
    winner = card.get("winner")
    if winner in {1, 2}:
        name = card.get("team1") if winner == 1 else card.get("team2")
        logo = card.get("logo1") if winner == 1 else card.get("logo2")
        team_id = card.get("team1_id") if winner == 1 else card.get("team2_id")
        other = card.get("team2") if winner == 1 else card.get("team1")
        bits.append(
            "<div class='hero'>"
            + _img(_team_logo_uri(str(team_id or ""), str(logo or "")), "tlogo")
            + f"<div class='name'>{_e(name or '?')}</div></div>"
        )
    else:
        other = ""
        bits.append(f"<div class='opp'>{_e(card.get('team1') or '?')}</div>")
        bits.append(f"<div class='opp'>{_e(card.get('team2') or '?')}</div>")
    bits.append(
        "<div class='hero-score'>"
        + f"<span class='num'>{_e(left)}</span><span class='dash'>–</span><span class='num'>{_e(right)}</span>"
        + "</div>"
    )
    if other:
        bits.append(f"<div class='opp'>对 {_e(other)}</div>")
    extra = (card.get("map_score") or "").strip()
    if extra:
        bits.append(f"<div class='opp'>{_e(extra)}</div>")
    bits.append(_map_strip(list(card.get("map_rows") or [])))
    return "".join(bits)


def _match_html(card: dict, height: int, width: int) -> str:
    kind = card.get("kind") or "score"
    accent = {"preview": "live", "final": "final", "soon": "soon"}.get(kind, "")
    pair = card.get("pair") or ("", "")
    left = pair[0] if pair and pair[0] else ""
    right = pair[1] if pair and len(pair) > 1 else ""
    if kind in {"map", "match"}:
        head = _winner_block(card)
    else:
        head = (
            f"<div class='kicker'>{_e(card.get('label'))}</div>"
            + _team_row(
                card.get("team1") or "?",
                left,
                card.get("logo1") or "",
                accent,
                team_id=str(card.get("team1_id") or ""),
            )
            + _team_row(
                card.get("team2") or "?",
                right,
                card.get("logo2") or "",
                accent,
                team_id=str(card.get("team2_id") or ""),
            )
            + _map_strip(list(card.get("map_rows") or []))
        )
    bits = [
        head,
        "<div class='rule'></div>",
        _event_block(
            str(card.get("event") or ""),
            str(card.get("tier") or ""),
            str(card.get("event_id") or ""),
            str(card.get("event_logo") or ""),
            size="chip",
        ),
    ]
    if card.get("note"):
        bits.append(f"<div class='note'>{_e(card.get('note'))}</div>")
    return _page("".join(bits), height, width)


def _tier_key(tier: str, name: str = "") -> str:
    if tier in {"Major", "T1", "T2", "T3", "Other"}:
        return tier
    from hltv_bot.events import classify_tier

    return classify_tier(name or "")


def _tier_class(tier: str) -> str:
    return {
        "Major": "tier-major",
        "T1": "tier-t1",
        "T2": "tier-t2",
        "T3": "tier-t3",
    }.get(tier or "", "tier-other")


def _tier_mark(tier: str) -> str:
    from hltv_bot.events import tier_label

    return f"<div class='tier {_tier_class(tier)}'>{_e(tier_label(tier))}</div>"


def _event_block(name: str, tier: str, event_id: str, logo_url: str, *, size: str = "chip", extra: str = "") -> str:
    key = _tier_key(tier, name)
    return (
        f"<div class='event-card event-{size}'>"
        + _event_bg(event_id, logo_url)
        + f"<div class='event-copy {_tier_class(key)}'>"
        + _tier_mark(key)
        + f"<div class='name'>{_e(name)}</div>"
        + extra
        + "</div></div>"
    )


def _event_bg(event_id: str, url: str) -> str:
    logo = _event_logo_uri(event_id, url, "l")
    if not logo.startswith("data:image"):
        return ""
    return (
        f"<div class='event-bg' style=\"background-image:url('{logo}')\"></div>"
        "<div class='event-shade'></div>"
    )


def _event_html(card: dict, height: int, width: int) -> str:
    bits = [
        "<div class='event-card event-solo'>",
        _event_bg(str(card.get("id") or ""), str(card.get("logo_url") or card.get("logo_small_url") or "")),
        f"<div class='event-copy {_tier_class(_tier_key(str(card.get('tier') or ''), str(card.get('name') or '')))}'>",
        "<div class='kicker'>赛事</div>",
        _tier_mark(_tier_key(str(card.get("tier") or ""), str(card.get("name") or ""))),
        f"<div class='name'>{_e(card.get('name'))}</div>",
    ]
    place = " ".join(x for x in (card.get("flag") or "", card.get("location") or "") if x)
    if place:
        bits.append(f"<div class='place'><span class='flag'>{card.get('flag') or ''}</span> {_e(card.get('location'))}</div>")
    bits.append("<div class='rule'></div>")
    if card.get("clock"):
        bits.append(f"<div class='when'>{_e(card.get('clock'))}   UTC+8</div>")
    if card.get("final"):
        bits.append("<div class='remain final'>最后提醒</div>")
    bits.append(f"<div class='remain'>{_e(card.get('remain'))}</div>")
    bits.append("</div></div>")
    return _page("".join(bits), height, width)


def _guide_html(card: dict, height: int, width: int) -> str:
    morning = int(card.get("morning") or 10)
    evening = int(card.get("evening") or 20)
    lines = [
        ("默认", "至少 1 星，并且赛事名是 Major / T1。"),
        ("比分", "0:0 只预告一次。同一张图只涨分。图结束是 Map winner，比赛结束是 Match winner。"),
        ("BO", "地图按顺序排开。赢下的图后面是那支队的图标。"),
        ("比赛日", f"UTC+8 {morning:02d}:00 到次日 {morning:02d}:00，含国外晚上打到凌晨的比赛。"),
        ("赛程", f"每天 {morning:02d}:00 发整日，{evening:02d}:00 发还没开的，含次日凌晨。"),
        ("补充", "/follow 单场。/cover 整赛事，每个比赛日都算。/ignore 摘掉一场。"),
        ("开关", "/watch 加入多场。/follow 加入单场。不带参数就是加入本群。/stop 全部关闭。"),
        ("赛事", "Major / Tier 1：进入窗口、剩 1 天、最后几小时。/track 打开。/window 7 6 可改。"),
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
    parts: list[str] = []
    if current:
        parts.append(f"<span class='mmap-now'>{_e(current)}</span>")
    for name in rest:
        parts.append(f"<span class='mmap-rest'>{_e(name)}</span>")
    if fmt:
        parts.append(f"<span class='mmap-fmt'>{_e(fmt)}</span>")
    if not parts:
        return ""
    joined = "<span class='mmap-sep'> · </span>".join(parts)
    return f"<div class='mmap'>{joined}</div>"


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
            + _event_block(
                str(row.get("event") or ""),
                str(row.get("tier") or ""),
                str(row.get("event_id") or ""),
                str(row.get("event_logo") or ""),
                extra=f"<div class='sub'>#{_e(mid)}</div>" if mid else "",
            )
            + _map_line(row)
            + "</div>"
        )
    if not rows:
        bits.append("<div class='mcard mbody'>没有比赛</div>")
    return _page("".join(bits), height, width)


def _events_html(card: dict, height: int, width: int) -> str:
    rows = list(card.get("rows") or [])[:8]
    bits = ["<div class='sheet-title'>赛事</div>"]
    for ev in rows:
        bits.append(
            "<div class='event-card event-row'>"
            + _event_bg(str(ev.get("id") or ""), str(ev.get("logo_url") or ""))
            + f"<div class='event-copy {_tier_class(_tier_key(str(ev.get('tier') or ''), str(ev.get('name') or '')))}'>"
            + _tier_mark(_tier_key(str(ev.get("tier") or ""), str(ev.get("name") or "")))
            + f"<div class='name'>{_e(ev.get('name'))}</div>"
        )
        place = " ".join(x for x in (ev.get("flag") or "", ev.get("location") or "") if x)
        if place:
            bits.append(f"<div class='place'><span class='flag'>{ev.get('flag') or ''}</span> {_e(ev.get('location'))}</div>")
        if ev.get("when"):
            bits.append(f"<div class='when'>{_e(ev.get('when'))}</div>")
        prize = (ev.get("prize") or "").strip()
        if prize and prize not in {"_", "TBA", "Other"}:
            bits.append(f"<div class='prize'>{_e(prize)}</div>")
        bits.append("</div></div>")
    if not rows:
        bits.append("<div class='sub'>没有赛事</div>")
    return _page("".join(bits), height, width)


def _stars(row: dict) -> int:
    try:
        return max(0, min(5, int(row.get("stars") or 0)))
    except (TypeError, ValueError):
        return 0
