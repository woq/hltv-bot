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
.name { flex: 1; font-size: 28px; line-height: 1; font-weight: 700; }
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
.elogo, .elogo-ph { height: 16px; width: auto; max-width: 48px; object-fit: contain; margin-right: 8px; vertical-align: middle; }
.eventline { display: flex; align-items: center; }
.rule { height: 1px; background: #2c2822; margin: 22px 0 16px; }
.event { font-size: 16px; color: #d9cbb6; }
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
.mbody .tlogo, .mbody .tlogo-ph { width: 16px; height: 16px; flex-basis: 16px; margin-right: 6px; }
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


def _event_logo_uri(event_id: str, url: str) -> str:
    url = (url or "").strip()
    event_id = str(event_id or "").strip()
    if url.startswith("data:image"):
        return url
    if event_id and url:
        try:
            from hltv_bot.events import ensure_event_logos, get_cached_logo_data_uri

            ensure_event_logos([(event_id, url)])
            found = get_cached_logo_data_uri(event_id)
            if found:
                return found
        except Exception:
            return ""
    return _logo_uri(url)


def render_card(card: dict) -> bytes:
    view = card.get("view") or "match"
    if view == "matches":
        height = 96 + 128 * max(1, min(len(card.get("rows") or []), 12))
        html = _matches_html(card, height, _LIST_W)
    elif view == "events":
        height = 118 + 88 * max(1, min(len(card.get("rows") or []), 8))
        html = _events_html(card, height, _LIST_W)
    elif view == "event":
        html = _event_html(card, 420, _CARD_W)
    else:
        height = 430 if card.get("streak") else 380
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
    if uri.startswith("data:image"):
        return f'<img class="{cls}" src="{uri}" />'
    return f'<span class="{cls}-ph"></span>'


def _team_row(name: str, score: str, logo: str, accent: str) -> str:
    mark = _e(score) if score else "–"
    return (
        "<div class='trow'>"
        + _img(_logo_uri(logo), "tlogo")
        + f"<div class='name'>{_e(name)}</div>"
        + f"<div class='sc {accent}'>{mark}</div>"
        + "</div>"
    )


def _match_html(card: dict, height: int, width: int) -> str:
    kind = card.get("kind") or "score"
    accent = {"live": "live", "final": "final", "soon": "soon"}.get(kind, "")
    pair = card.get("pair") or ("", "")
    left = pair[0] if pair and pair[0] else ""
    right = pair[1] if pair and len(pair) > 1 else ""
    bits = [
        f"<div class='kicker'>{_e(card.get('label'))}</div>",
        _team_row(card.get("team1") or "?", left, card.get("logo1") or "", accent),
        _team_row(card.get("team2") or "?", right, card.get("logo2") or "", accent),
        "<div class='rule'></div>",
        "<div class='eventline'>"
        + _img(_logo_uri(card.get("event_logo") or ""), "elogo")
        + f"<div class='event'>{_e(card.get('event'))}</div></div>",
    ]
    if card.get("map"):
        bits.append(f"<div class='when'>{_e(card.get('map'))}</div>")
    if card.get("clock"):
        bits.append(f"<div class='when'>{_e(card.get('clock'))}   UTC+8</div>")
    if card.get("streak"):
        bits.append(f"<div class='streak'>⚡  {_e(card.get('streak'))}</div>")
    return _page("".join(bits), height, width)


def _event_html(card: dict, height: int, width: int) -> str:
    logo = _event_logo_uri(str(card.get("id") or ""), str(card.get("logo_url") or ""))
    bg = ""
    if logo.startswith("data:image"):
        bg = f"<div class='event-bg' style=\"background-image:url('{logo}')\"></div><div class='event-shade'></div>"
    bits = [
        "<div class='event-card'>",
        bg,
        "<div class='event-copy'>",
        f"<div class='kicker'>赛事  ·  {_e(card.get('tier'))}</div>",
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


def _matches_html(card: dict, height: int, width: int) -> str:
    rows = list(card.get("rows") or [])[:12]
    bits = ["<div class='sheet-title'>比赛  ·  UTC+8</div>"]
    for row in rows:
        live = row.get("live") == "1"
        a = (row.get("score1") or "").strip()
        b = (row.get("score2") or "").strip()
        clock = row.get("time") or ""
        stars = "★" * _stars(row)
        slot_cls = "slot" if live else "slot off"
        bits.append(
            "<tr>"
            f"<td class='{slot_cls}'><div>LIVE</div></td>"
            "<td class='body'>"
            + _team_row(row.get("team1") or "?", a, row.get("team1_logo") or "", "")
            + _team_row(row.get("team2") or "?", b, row.get("team2_logo") or "", "")
            + "<div class='sub'>"
            + _img(_logo_uri(row.get("event_logo") or ""), "elogo")
            + f"{_e(clock)}   {_e(stars)}   {_e(row.get('event'))}</div>"
            + "</td></tr>"
        )
    if not rows:
        bits.append("<tr><td class='slot off'><div>LIVE</div></td><td class='body'>没有比赛</td></tr>")
    table = "<table class='sheet'>" + "".join(bits[1:]) + "</table>"
    return _page(bits[0] + table, height, width)


def _events_html(card: dict, height: int, width: int) -> str:
    rows = list(card.get("rows") or [])[:8]
    bits = ["<div class='sheet-title'>赛事</div>"]
    for ev in rows:
        logo = _event_logo_uri(str(ev.get("id") or ""), str(ev.get("logo_url") or ""))
        bg = ""
        if logo.startswith("data:image"):
            bg = f"<div class='event-bg' style=\"background-image:url('{logo}')\"></div><div class='event-shade'></div>"
        bits.append(
            "<div class='event-card' style='margin-top:10px;padding-top:8px;border-top:1px solid #2c2822'>"
            + bg
            + "<div class='event-copy'>"
            + f"<div class='name' style='font-size:16px'>{_e(ev.get('name'))}</div>"
            + "<div class='sub'>"
            + f"{_e(ev.get('tier'))}   {ev.get('flag') or ''} {_e(ev.get('location'))}   {_e(ev.get('when'))}"
            + "</div></div></div>"
        )
    if not rows:
        bits.append("<div class='sub'>没有赛事</div>")
    return _page("".join(bits), height, width)


def _stars(row: dict) -> int:
    try:
        return max(0, min(5, int(row.get("stars") or 0)))
    except (TypeError, ValueError):
        return 0
