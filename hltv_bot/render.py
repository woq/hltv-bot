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
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore

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
    logo_dir = os.path.join(os.path.dirname(__file__), "assets", "logos")
    svg_path = os.path.join(logo_dir, f"{norm}.svg")
    png_path = os.path.join(logo_dir, f"{norm}.png")

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
    star_path = '<svg width="14" height="14" viewBox="0 0 24 24" fill="#f59e0b" style="display:inline-block;vertical-align:middle;margin:0 1px;"><polygon points="12,2 15,9 22,9 17,14 19,21 12,17 5,21 7,14 2,9 9,9"/></svg>'
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

    # Estimate content height for dynamic page sizing
    row_count = len(filtered)
    sec_count = len(sorted_tiers)
    calc_height = max(160, 60 + sec_count * 36 + row_count * 48 + 40)

    html_parts = [
        f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: 640px {calc_height}px;
    margin: 0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #12151b;
    color: #e2e8f0;
    font-family: DejaVu Sans, Liberation Sans, -apple-system, sans-serif;
    font-size: 13px;
    width: 640px;
    height: {calc_height}px;
    padding: 16px 20px 12px 20px;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #232936;
    padding-bottom: 8px;
    margin-bottom: 12px;
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
    margin-top: 10px;
  }}
  .tier-hdr {{
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 6px;
    display: flex;
    align-items: center;
  }}
  .tier-hdr.T1 {{ color: #f87171; }}
  .tier-hdr.T2 {{ color: #fbbf24; }}
  .tier-hdr.T3 {{ color: #60a5fa; }}
  .tier-hdr.Other {{ color: #94a3b8; }}
  .table {{
    display: flex;
    flex-direction: column;
    gap: 5px;
  }}
  .row {{
    background: #181d26;
    border-radius: 6px;
    padding: 8px 12px;
    display: flex;
    align-items: center;
    border: 1px solid #232a38;
    height: 42px;
  }}
  .row.live {{
    border-color: #ef4444;
    background: #24161b;
  }}
  .time-col {{
    width: 72px;
    font-size: 13px;
    font-weight: 700;
    color: #94a3b8;
    display: flex;
    align-items: center;
  }}
  .time-col.live {{
    color: #f87171;
  }}
  .live-dot {{
    width: 7px;
    height: 7px;
    background: #ef4444;
    border-radius: 50%;
    display: inline-block;
    margin-right: 6px;
  }}
  .match-col {{
    flex: 1;
    display: flex;
    align-items: center;
    gap: 8px;
    overflow: hidden;
  }}
  .team-unit {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .team-logo {{
    width: 20px;
    height: 20px;
    object-fit: contain;
    border-radius: 3px;
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
  .team {{
    font-weight: 700;
    color: #ffffff;
    font-size: 14px;
    white-space: nowrap;
  }}
  .vs {{
    font-size: 12px;
    color: #64748b;
    font-weight: 600;
    margin: 0 4px;
  }}
  .event-tag {{
    font-size: 11px;
    color: #64748b;
    margin-left: 8px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 140px;
  }}
  .stars-wrap {{
    margin-left: auto;
    padding-right: 12px;
    display: flex;
    align-items: center;
  }}
  .id-col {{
    font-family: monospace;
    font-size: 13px;
    color: #38bdf8;
    font-weight: 700;
  }}
  .footer {{
    text-align: center;
    font-size: 11px;
    color: #64748b;
    margin-top: 12px;
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
            html_parts.append(f'<div class="tier-sec"><div class="tier-hdr {t}">{html.escape(title)}</div><div class="table">')
            for m in grouped[t]:
                is_live = m.get("live") == "1"
                row_cls = "row live" if is_live else "row"
                time_cls = "time-col live" if is_live else "time-col"
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
                <div class="{row_cls}">
                  <div class="{time_cls}">{time_html}</div>
                  <div class="match-col">
                    <div class="team-unit">{t1_icon}<span class="team">{html.escape(t1)}</span></div>
                    <span class="vs">vs</span>
                    <div class="team-unit">{t2_icon}<span class="team">{html.escape(t2)}</span></div>
                    {f'<span class="event-tag">{ev}</span>' if ev else ''}
                  </div>
                  <div class="stars-wrap">{stars_html}</div>
                  <div class="id-col">#{mid}</div>
                </div>
                """)
            html_parts.append('</div></div>')

    html_parts.append('<div class="footer">/watch &lt;id&gt; to stream live scorebot</div></body></html>')
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
    pixmap = page.render(scale=1.5)  # 1.5x crisp rendering (960px high-res)
    pil_image = pixmap.to_pil()

    out = io.BytesIO()
    pil_image.save(out, format="PNG")
    return out.getvalue()
