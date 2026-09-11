from __future__ import annotations

import base64
import html
import io
import json
import logging
import os
import re
from typing import Sequence

try:
    import weasyprint
    import pypdfium2
except ImportError:
    weasyprint = None
    pypdfium2 = None

try:
    from PIL import Image, ImageChops
except ImportError:
    Image = None  # type: ignore
    ImageChops = None  # type: ignore

log = logging.getLogger("hltv_bot.render")

_TIER_KEYWORDS = {
    "T1": [
        "major", "pgl", "iem", "katowice", "cologne",
        "blast", "esl pro league", "epl", "world final",
    ],
    "T2": [
        "cct", "challenger league", "ecl", "res", "yalla",
        "compass", "thunderpick", "mesa", "fiesta", "nodwin", "starladder",
    ],
    "T3": [
        "closed qualifier", "open qualifier", "qualifier",
        "cash cup", "academy", "regional cup", "series qualifier", "esea",
    ],
}

_TEAM_ALIASES = {
    "natusvincere": "navi",
    "furiagaming": "furia",
    "ninjasinpyjamas": "nip",
    "cloud9": "c9",
    "themongolz": "mongolz",
    "virtuspro": "vp",
}


def classify_event_tier(event_name: str, stars: int = 0) -> str:
    """Classify match into T1, T2, T3 or Other."""
    ev = (event_name or "").lower()
    if stars >= 4:
        return "T1"

    is_qualifier = bool(re.search(r"\b(qualifier|closed|open\s+qualifier)\b", ev))

    for kw in _TIER_KEYWORDS["T1"]:
        if kw in ev:
            if is_qualifier:
                return "T2" if stars >= 1 else "T3"
            return "T1"

    if stars >= 2:
        return "T2"

    for kw in _TIER_KEYWORDS["T2"]:
        if kw in ev:
            if is_qualifier:
                return "T3"
            return "T2"

    for kw in _TIER_KEYWORDS["T3"]:
        if kw in ev:
            return "T3"

    if stars == 1:
        return "T3"

    return "Other"


def tier_rank(tier: str) -> int:
    return {"T1": 1, "T2": 2, "T3": 3, "Other": 4}.get(tier, 5)


def localize_team(name: str) -> str:
    return name


BADGE_COLORS = [
    ("#2b3945", "#90cdf4"),
    ("#3b2f45", "#d6bcfa"),
    ("#2f3e35", "#9ae6b4"),
    ("#45382b", "#fbd38d"),
    ("#452b2b", "#feb2b2"),
    ("#2b3f3e", "#81e6d9"),
]


def _get_badge_style(name: str) -> tuple[str, str]:
    h = 0
    for char in name:
        h = (h << 5) - h + ord(char)
    return BADGE_COLORS[abs(h) % len(BADGE_COLORS)]


def _get_initials(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9]", "", name or "")
    if not clean:
        return "?"
    if len(clean) <= 3:
        return clean.upper()
    return clean[:2].upper()


def _render_team_icon(name: str) -> str:
    norm = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    norm_alias = _TEAM_ALIASES.get(norm, norm)
    logo_dir = os.path.join(os.path.dirname(__file__), "assets", "logos")

    for candidate in (norm, norm_alias):
        if not candidate:
            continue
        svg_path = os.path.join(logo_dir, f"{candidate}.svg")
        png_path = os.path.join(logo_dir, f"{candidate}.png")

        if os.path.exists(svg_path):
            try:
                with open(svg_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                    return f'<img class="team-logo" src="data:image/svg+xml;base64,{b64}" alt="{html.escape(name)}" />'
            except Exception:
                pass

        if os.path.exists(png_path):
            try:
                with open(png_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
                    return f'<img class="team-logo" src="data:image/png;base64,{b64}" alt="{html.escape(name)}" />'
            except Exception:
                pass

    bg, fg = _get_badge_style(name)
    initials = _get_initials(name)
    return f'<span class="team-badge" style="background:{bg};color:{fg};">{html.escape(initials)}</span>'


def _star_svg(count: int) -> str:
    if count <= 0:
        return ""
    star_path = '<svg width="13" height="13" viewBox="0 0 24 24" fill="#f59e0b" style="display:inline-block;vertical-align:middle;margin:0 1px;"><polygon points="12,2 15,9 22,9 17,14 19,21 12,17 5,21 7,14 2,9 9,9"/></svg>'
    return f'<span class="stars">{"".join(star_path for _ in range(count))}</span>'


def build_matches_html(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    updated_at: str = "",
) -> str:
    max_rank = tier_rank(tier_filter)
    filtered = []
    for r in rows:
        stars = int(r.get("stars") or 0)
        t = classify_event_tier(r.get("event") or "", stars)
        r_copy = dict(r)
        r_copy["_tier"] = t
        if tier_rank(t) <= max_rank:
            filtered.append(r_copy)

    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    sorted_tiers = sorted(grouped.keys(), key=tier_rank)

    tier_titles = {
        "T1": "• TIER 1 / MAJOR & BIG EVENTS",
        "T2": "• TIER 2 / CHALLENGER & CIRCUIT",
        "T3": "• TIER 3 / QUALIFIERS & CUPS",
        "Other": "• OTHER MATCHES",
    }

    row_count = len(filtered)
    sec_count = len(sorted_tiers)
    calc_height = max(130, 52 + sec_count * 34 + row_count * 47 + 16)

    html_parts = [
        f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: 720px {calc_height}px;
    margin: 0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #12151b;
    color: #e2e8f0;
    font-family: DejaVu Sans, Liberation Sans, -apple-system, sans-serif;
    font-size: 13px;
    width: 720px;
    height: {calc_height}px;
    padding: 14px 18px 10px 18px;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #232936;
    padding-bottom: 7px;
    margin-bottom: 10px;
  }}
  .header-title {{
    font-size: 17px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 0.5px;
  }}
  .header-sub {{
    font-size: 13px;
    color: #94a3b8;
    font-weight: 500;
  }}
  .tier-sec {{
    margin-top: 8px;
  }}
  .tier-hdr {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 5px;
    display: flex;
    align-items: center;
  }}
  .tier-hdr.T1 {{ color: #f87171; }}
  .tier-hdr.T2 {{ color: #fbbf24; }}
  .tier-hdr.T3 {{ color: #60a5fa; }}
  .tier-hdr.Other {{ color: #94a3b8; }}
  .match-table {{
    width: 100%;
    table-layout: fixed;
    border-collapse: separate;
    border-spacing: 0 5px;
  }}
  .row {{
    background: #181d26;
    height: 42px;
  }}
  .row.live {{
    background: #24161b;
  }}
  .row td {{
    vertical-align: middle;
    border-top: 1px solid #232a38;
    border-bottom: 1px solid #232a38;
  }}
  .row.live td {{
    border-top-color: #ef4444;
    border-bottom-color: #ef4444;
  }}
  .row td:first-child {{
    border-left: 1px solid #232a38;
    border-top-left-radius: 6px;
    border-bottom-left-radius: 6px;
    padding-left: 12px;
  }}
  .row.live td:first-child {{
    border-left-color: #ef4444;
  }}
  .row td:last-child {{
    border-right: 1px solid #232a38;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
    padding-right: 12px;
  }}
  .row.live td:last-child {{
    border-right-color: #ef4444;
  }}
  .time-td {{
    width: 68px;
    font-size: 13px;
    font-weight: 700;
    color: #94a3b8;
    white-space: nowrap;
  }}
  .time-td.live {{
    color: #f87171;
  }}
  .live-dot {{
    width: 7px;
    height: 7px;
    background: #ef4444;
    border-radius: 50%;
    display: inline-block;
    margin-right: 5px;
  }}
  .team-td {{
    width: 195px;
    max-width: 195px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .team-unit {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    max-width: 195px;
    overflow: hidden;
  }}
  .team-logo {{
    width: 20px;
    height: 20px;
    object-fit: contain;
    border-radius: 3px;
    flex-shrink: 0;
  }}
  .team-badge {{
    display: inline-block;
    text-align: center;
    line-height: 18px;
    width: 24px;
    height: 18px;
    font-size: 10px;
    font-weight: 700;
    font-family: monospace;
    border-radius: 3px;
    flex-shrink: 0;
  }}
  .team-name {{
    font-weight: 700;
    color: #ffffff;
    font-size: 13.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .vs-td {{
    width: 26px;
    text-align: center;
    font-size: 12px;
    color: #64748b;
    font-weight: 600;
  }}
  .event-td {{
    width: 100px;
    font-size: 11px;
    color: #64748b;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    padding-left: 6px;
    max-width: 100px;
  }}
  .stars-td {{
    width: 70px;
    text-align: right;
    white-space: nowrap;
    padding-right: 6px;
  }}
  .id-td {{
    width: 66px;
    text-align: right;
    font-family: monospace;
    font-size: 13px;
    color: #38bdf8;
    font-weight: 700;
    white-space: nowrap;
  }}
</style>
</head>
<body>
  <div class="header">
    <div class="header-title">HLTV MATCHES</div>
    <div class="header-sub">{html.escape(f"{updated_at} · {tier_filter}" if updated_at else tier_filter)}</div>
  </div>
"""
    ]

    if not filtered:
        html_parts.append(
            f'<div style="text-align:center;padding:30px;color:#64748b;font-size:14px;">No matches found for {html.escape(tier_filter)}</div>'
        )
    else:
        for t in sorted_tiers:
            title = tier_titles.get(t, f"• {t}")
            html_parts.append(f'<div class="tier-sec"><div class="tier-hdr {t}">{html.escape(title)}</div><table class="match-table">')
            for m in grouped[t]:
                is_live = m.get("live") == "1"
                row_cls = "row live" if is_live else "row"
                time_cls = "time-td live" if is_live else "time-td"
                if is_live:
                    time_html = '<span class="live-dot"></span>LIVE'
                else:
                    time_html = html.escape(m.get("time") or "--:--")

                t1 = m.get("team1") or "?"
                t2 = m.get("team2") or "?"
                t1_icon = _render_team_icon(t1)
                t2_icon = _render_team_icon(t2)
                stars_val = int(m.get("stars") or 0)
                stars_html = _star_svg(stars_val)
                mid = html.escape(m.get("id") or "")
                ev = html.escape(m.get("event") or "")

                html_parts.append(f"""
                <tr class="{row_cls}">
                  <td class="{time_cls}">{time_html}</td>
                  <td class="team-td">
                    <div class="team-unit">{t1_icon}<span class="team-name">{html.escape(t1)}</span></div>
                  </td>
                  <td class="vs-td">vs</td>
                  <td class="team-td">
                    <div class="team-unit">{t2_icon}<span class="team-name">{html.escape(t2)}</span></div>
                  </td>
                  <td class="event-td">{ev}</td>
                  <td class="stars-td">{stars_html}</td>
                  <td class="id-td">#{mid}</td>
                </tr>
                """)
            html_parts.append('</table></div>')

    html_parts.append('</body></html>')
    return "".join(html_parts)


def render_matches_image(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    title_suffix: str = "",
    updated_at: str = "",
) -> bytes:
    """Render matches using Python native WeasyPrint (HTML+CSS) with pypdfium2."""
    if weasyprint is None or pypdfium2 is None:
        raise RuntimeError("weasyprint and pypdfium2 are required for HTML/CSS rendering")

    html_content = build_matches_html(rows, tier_filter=tier_filter, updated_at=updated_at)
    pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
    doc = pypdfium2.PdfDocument(pdf_bytes)
    page = doc[0]
    pixmap = page.render(scale=1.5)  # 1.5x crisp rendering (1050px high-res)
    pil_image = pixmap.to_pil()

    # Autocrop excess bottom blank space if any
    if ImageChops is not None:
        try:
            bg = Image.new("RGB", pil_image.size, (18, 21, 27))
            diff = ImageChops.difference(pil_image.convert("RGB"), bg)
            bbox = diff.getbbox()
            if bbox and bbox[3] < pil_image.height - 10:
                pil_image = pil_image.crop((0, 0, pil_image.width, min(pil_image.height, bbox[3] + 18)))
        except Exception as e:
            log.debug("autocrop skipped: %s", e)

    out = io.BytesIO()
    pil_image.save(out, format="PNG")
    return out.getvalue()
