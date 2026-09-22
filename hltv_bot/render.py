from __future__ import annotations

import html
import io
import logging
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


def _render_team_icon(name: str, logo_url: str = "") -> str:
    """Logo from the matches page cache. Unknown teams get initials, not a bundled file."""
    if logo_url:
        from hltv_bot.team_logos import cached_data_uri

        uri = cached_data_uri(logo_url)
        if uri:
            return f'<img class="team-logo" src="{uri}" alt="{html.escape(name)}" />'
    bg, fg = _get_badge_style(name)
    initials = _get_initials(name)
    return f'<span class="team-badge" style="background:{bg};color:{fg};">{html.escape(initials)}</span>'


_TROPHY_SVG = (
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fbbf24" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" '
    'style="display:inline-block;vertical-align:middle;margin-right:6px;">'
    '<path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6"/>'
    '<path d="M18 9h1.5a2.5 2.5 0 0 0 0-5H18"/>'
    '<path d="M4 22h16"/>'
    '<path d="M10 14.66V17c0 .55-.47.98-.97 1.21C7.85 18.75 7 20.24 7 22"/>'
    '<path d="M14 14.66V17c0 .55.47.98.97 1.21C16.15 18.75 17 20.24 17 22"/>'
    '<path d="M18 2H6v7a6 6 0 0 0 12 0V2Z" fill="#f59e0b"/>'
    '</svg>'
)


def _event_banner_logo(rows: Sequence[dict]) -> str:
    from hltv_bot.events import get_cached_logo_data_uri

    for row in rows:
        eid = str(row.get("event_id") or "")
        if not eid:
            continue
        uri = get_cached_logo_data_uri(eid)
        if uri:
            return f'<img class="event-logo" src="{uri}" alt="" />'
    return _TROPHY_SVG


def _matches_empty_copy(tier_filter: str) -> tuple[str, str]:
    hints = {
        "T1": "Nothing scheduled for T1 · try /matches t2",
        "T2": "Nothing scheduled for T2 · try /matches t3",
        "T3": "Nothing scheduled for T3",
        "Other": "Nothing listed",
    }
    return "No matches", hints.get(tier_filter, f"Nothing scheduled for {tier_filter}")


def _events_empty_copy(tier_filter: str) -> tuple[str, str]:
    label = tier_filter or "Major / T1"
    if label == "Major":
        sub = "No majors in the next 3 months · try /events t2"
    elif "All" in label:
        sub = "No tournaments in the next 3 months"
    elif "T2" in label:
        sub = "Nothing in this filter · try /events all"
    else:
        sub = "Nothing scheduled · try /events t2"
    return "No tournaments", sub


def _star_svg(count: int) -> str:
    if count <= 0:
        return ""
    star_path = '<svg width="13" height="13" viewBox="0 0 24 24" fill="#f59e0b" style="display:inline-block;vertical-align:middle;margin:0 1px;"><polygon points="12,2 15,9 22,9 17,14 19,21 12,17 5,21 7,14 2,9 9,9"/></svg>'
    return f'<span class="stars">{"".join(star_path for _ in range(count))}</span>'


def build_matches_html(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T1",
    updated_at: str = "",
) -> str:
    max_rank = tier_rank(tier_filter)
    # 1. 统一赛事的最高 Tier：避免同一个赛事因比赛星级不同被分拆到多个 Tier 横幅
    event_tier_map: dict[str, str] = {}
    for r in rows:
        ev = r.get("event") or "Other Matches"
        st = int(r.get("stars") or 0)
        t = classify_event_tier(ev, st)
        if ev not in event_tier_map or tier_rank(t) < tier_rank(event_tier_map[ev]):
            event_tier_map[ev] = t

    filtered = []
    for r in rows:
        _u1 = (r.get("team1") or "").strip().upper()
        _u2 = (r.get("team2") or "").strip().upper()
        if (not _u1 or _u1 in ("?", "TBD")) and (not _u2 or _u2 in ("?", "TBD")):
            continue
        stars = int(r.get("stars") or 0)
        ev = r.get("event") or "Other Matches"
        t = event_tier_map.get(ev, classify_event_tier(ev, stars))
        r_copy = dict(r)
        r_copy["_tier"] = t
        if tier_filter == "Other":
            filtered.append(r_copy)
        elif tier_rank(t) <= max_rank and stars >= 1:
            filtered.append(r_copy)

    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    sorted_tiers = sorted(grouped.keys(), key=tier_rank)

    # Count unique events per tier to accurately calculate total height
    total_event_headers = sum(len({m.get("event") or "Other Matches" for m in grouped[t]}) for t in sorted_tiers)
    row_count = len(filtered)
    if not filtered:
        calc_height = 280
    else:
        calc_height = max(130, 56 + total_event_headers * 38 + row_count * 45 + 24)

    html_parts = [
        f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: 780px {calc_height}px;
    margin: 0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #12151b;
    color: #e2e8f0;
    font-family: DejaVu Sans, Liberation Sans, -apple-system, sans-serif;
    font-size: 13px;
    width: 780px;
    height: {calc_height}px;
    padding: 14px 18px 10px 18px;
  }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    border-bottom: 2px solid #232936;
    padding-bottom: 7px;
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
  .empty-card {{
    margin-top: 18px;
    background: #181d26;
    border: 1px dashed #334155;
    border-radius: 8px;
    text-align: center;
    padding: 36px 20px 32px 20px;
  }}
  .empty-title {{
    font-size: 16px;
    font-weight: 800;
    color: #e2e8f0;
    letter-spacing: 0.4px;
  }}
  .empty-sub {{
    margin-top: 8px;
    font-size: 13px;
    color: #94a3b8;
  }}
  .event-block {{
    margin-bottom: 10px;
  }}
  .event-banner {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #181d26;
    border-left: 3.5px solid #38bdf8;
    padding: 6px 12px;
    margin-bottom: 4px;
    border-radius: 3px 5px 5px 3px;
  }}
  .event-banner.T1 {{ border-left-color: #f87171; background: #23181c; }}
  .event-banner.T2 {{ border-left-color: #fbbf24; background: #231f16; }}
  .event-banner.T3 {{ border-left-color: #60a5fa; background: #161e2b; }}
  .event-banner.Other {{ border-left-color: #94a3b8; background: #181d26; }}
  .event-name {{
    font-size: 12.5px;
    font-weight: 700;
    color: #f1f5f9;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    display: inline-flex;
    align-items: center;
  }}
  .event-logo {{
    width: 16px;
    height: 16px;
    max-width: 16px;
    max-height: 16px;
    object-fit: contain;
    margin-right: 7px;
    vertical-align: middle;
    display: inline-block;
  }}
  .event-banner.T1 .event-name {{ color: #fca5a5; }}
  .event-banner.T2 .event-name {{ color: #fde68a; }}
  .event-banner.T3 .event-name {{ color: #93c5fd; }}
  .event-meta {{
    font-size: 11px;
    color: #94a3b8;
    font-weight: 600;
    white-space: nowrap;
    margin-left: 12px;
    display: inline-flex;
    align-items: center;
    gap: 8px;
  }}
  .event-tier-badge {{
    font-size: 10.5px;
    font-weight: 700;
    padding: 1px 7px;
    border-radius: 3px;
    font-family: monospace;
    letter-spacing: 0.5px;
  }}
  .event-tier-badge.Major {{ background: #3b1848; color: #e9d5ff; border: 1px solid #86198f; }}
  .event-tier-badge.T1 {{ background: #451a20; color: #fca5a5; border: 1px solid #7f1d1d; }}
  .event-tier-badge.T2 {{ background: #3b2a14; color: #fde68a; border: 1px solid #78350f; }}
  .event-tier-badge.T3 {{ background: #172554; color: #93c5fd; border: 1px solid #1e3a8a; }}
  .event-tier-badge.Other {{ background: #1e293b; color: #94a3b8; border: 1px solid #334155; }}
  .match-table {{
    width: 100%;
    table-layout: fixed;
    border-collapse: separate;
    border-spacing: 0 4px;
  }}
  .row {{
    background: #181d26;
    height: 40px;
  }}
  .row.live {{
    background: #24161b;
  }}
  .row td {{
    vertical-align: middle;
    border-top: 1px solid #232a38;
    border-bottom: 1px solid #232a38;
    padding: 0 4px;
  }}
  .row.live td {{
    border-top-color: #ef4444;
    border-bottom-color: #ef4444;
  }}
  .row td:first-child {{
    border-left: 1px solid #232a38;
    border-top-left-radius: 5px;
    border-bottom-left-radius: 5px;
    padding-left: 12px;
  }}
  .row.live td:first-child {{
    border-left-color: #ef4444;
  }}
  .row td:last-child {{
    border-right: 1px solid #232a38;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    padding-right: 12px;
  }}
  .row.live td:last-child {{
    border-right-color: #ef4444;
  }}
  .time-td {{
    font-size: 12px;
    font-weight: 700;
    color: #94a3b8;
    white-space: nowrap;
    overflow: hidden;
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
    vertical-align: middle;
  }}
  .team-td {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .team-unit {{
    display: inline-flex;
    align-items: center;
    vertical-align: middle;
    gap: 7px;
    width: 100%;
    max-width: 100%;
    overflow: hidden;
  }}
  .team-logo {{
    width: 20px;
    height: 20px;
    max-width: 20px;
    max-height: 20px;
    object-fit: contain;
    border-radius: 3px;
    flex-shrink: 0;
    display: inline-block;
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
    vertical-align: middle;
  }}
  .team-name {{
    font-weight: 700;
    color: #ffffff;
    font-size: 13.5px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    vertical-align: middle;
  }}
  .vs-td {{
    text-align: center;
    font-size: 12px;
    color: #64748b;
    font-weight: 600;
    white-space: nowrap;
  }}
  .meta-right-td {{
    text-align: right;
    white-space: nowrap;
    padding-right: 12px;
  }}
  .stars {{
    display: inline-block;
    vertical-align: middle;
    margin-right: 6px;
  }}
  .id-val {{
    display: inline-block;
    vertical-align: middle;
    font-family: monospace;
    font-size: 13px;
    color: #38bdf8;
    font-weight: 700;
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

    colgroup_html = """
    <colgroup>
      <col style="width: 95px;">
      <col style="width: 240px;">
      <col style="width: 28px;">
      <col style="width: 240px;">
      <col style="width: 141px;">
    </colgroup>
    """

    if not filtered:
        empty_title, empty_sub = _matches_empty_copy(tier_filter)
        html_parts.append(
            f"""
            <div class="empty-card">
              <div class="empty-title">{html.escape(empty_title)}</div>
              <div class="empty-sub">{html.escape(empty_sub)}</div>
            </div>
            """
        )
    else:
        for t in sorted_tiers:
            t_matches = grouped[t]
            ev_map: dict[str, list[dict]] = {}
            for m in t_matches:
                ev = m.get("event") or "Other Matches"
                ev_map.setdefault(ev, []).append(m)

            for ev, ms in ev_map.items():
                def _row_sort_key(m: dict) -> tuple:
                    is_live = 0 if m.get("live") == "1" else 1
                    _t1 = (m.get("team1") or "").strip().upper()
                    _t2 = (m.get("team2") or "").strip().upper()
                    has_tbd = 1 if (not _t1 or not _t2 or _t1 in ("?", "TBD") or _t2 in ("?", "TBD")) else 0
                    stars_val = int(m.get("stars") or 0)
                    time_val = str(m.get("time") or "")
                    return (is_live, has_tbd, -stars_val, time_val)

                ms = sorted(ms, key=_row_sort_key)
                m_count_str = f"{len(ms)} MATCH{'ES' if len(ms) > 1 else ''}"
                if t == "T1" and "major" in ev.lower():
                    tier_label = "[Major]"
                    tier_cls = "Major"
                elif t == "T1":
                    tier_label = "[Tier 1]"
                    tier_cls = "T1"
                elif t == "T2":
                    tier_label = "[Tier 2]"
                    tier_cls = "T2"
                elif t == "T3":
                    tier_label = "[Tier 3]"
                    tier_cls = "T3"
                else:
                    tier_label = ""
                    tier_cls = "Other"

                tier_badge_html = f'<span class="event-tier-badge {tier_cls}">{tier_label}</span>' if tier_label else ''
                from hltv_bot.events import clean_event_display_name

                banner_name = clean_event_display_name(ev)
                html_parts.append(f"""
                <div class="event-block">
                  <div class="event-banner {t}">
                    <span class="event-name">{_event_banner_logo(ms)}{html.escape(banner_name)}</span>
                    <span class="event-meta">{tier_badge_html}<span>{m_count_str}</span></span>
                  </div>
                  <table class="match-table">{colgroup_html}
                """)
                for m in ms:
                    is_live = m.get("live") == "1"
                    row_cls = "row live" if is_live else "row"
                    time_cls = "time-td live" if is_live else "time-td"
                    if is_live:
                        time_html = '<span class="live-dot"></span>LIVE'
                    else:
                        time_html = html.escape(m.get("time") or "--:--")

                    t1 = m.get("team1") or "?"
                    t2 = m.get("team2") or "?"
                    t1_icon = _render_team_icon(t1, str(m.get("team1_logo") or ""))
                    t2_icon = _render_team_icon(t2, str(m.get("team2_logo") or ""))
                    stars_val = int(m.get("stars") or 0)
                    stars_html = _star_svg(stars_val)
                    mid = html.escape(m.get("id") or "")

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
                      <td class="meta-right-td">{stars_html}<span class="id-val">#{mid}</span></td>
                    </tr>
                    """)
                html_parts.append('</table></div>')

    html_parts.append('</body></html>')
    return "".join(html_parts)


def render_matches_image(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T1",
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


def build_events_html(
    events: Sequence[dict],
    *,
    tier_filter: str = "Major / T1",
    updated_at: str = "",
    limit: int = 15,
) -> str:
    """Build HTML for HLTV Events list image (English-only, high-res 880px layout)."""
    from hltv_bot.events import format_location, get_cached_logo_data_uri, clean_event_display_name, format_event_date_range

    events_slice = list(events[:limit])
    row_count = len(events_slice)
    if not events_slice:
        calc_height = 280
    else:
        calc_height = max(140, 68 + row_count * 48 + 32)

    html_parts = [
        f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{
    size: 960px {calc_height}px;
    margin: 0;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #12151b;
    color: #e2e8f0;
    font-family: DejaVu Sans, Liberation Sans, -apple-system, sans-serif;
    font-size: 13px;
    width: 960px;
    height: {calc_height}px;
    padding: 16px 22px 14px 22px;
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
    font-size: 18px;
    font-weight: 800;
    color: #ffffff;
    letter-spacing: 0.6px;
  }}
  .header-sub {{
    font-size: 13px;
    color: #94a3b8;
    font-weight: 500;
  }}
  .empty-card {{
    margin-top: 18px;
    background: #181d26;
    border: 1px dashed #334155;
    border-radius: 8px;
    text-align: center;
    padding: 36px 20px 32px 20px;
  }}
  .empty-title {{
    font-size: 16px;
    font-weight: 800;
    color: #e2e8f0;
    letter-spacing: 0.4px;
  }}
  .empty-sub {{
    margin-top: 8px;
    font-size: 13px;
    color: #94a3b8;
  }}
  .event-tier-badge {{
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 4px;
    font-family: monospace;
    letter-spacing: 0.5px;
    display: inline-block;
  }}
  .event-tier-badge.Major {{ background: #3b1848; color: #e9d5ff; border: 1px solid #86198f; }}
  .event-tier-badge.T1 {{ background: #451a20; color: #fca5a5; border: 1px solid #7f1d1d; }}
  .event-tier-badge.T2 {{ background: #3b2a14; color: #fde68a; border: 1px solid #78350f; }}
  .event-tier-badge.T3 {{ background: #172554; color: #93c5fd; border: 1px solid #1e3a8a; }}
  .event-tier-badge.Other {{ background: #1e293b; color: #94a3b8; border: 1px solid #334155; }}
  .match-table {{
    width: 916px;
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
    padding: 0 8px;
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
    padding-right: 16px;
  }}
  .row.live td:last-child {{
    border-right-color: #ef4444;
  }}
  .countdown-td {{
    font-size: 12px;
    font-weight: 700;
    color: #38bdf8;
    white-space: nowrap;
  }}
  .countdown-td.live {{
    color: #f87171;
  }}
  .live-dot {{
    width: 7px;
    height: 7px;
    background: #ef4444;
    border-radius: 50%;
    display: inline-block;
    margin-right: 5px;
    vertical-align: middle;
  }}
  .event-name-td {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    font-weight: 700;
    color: #ffffff;
    font-size: 13px;
  }}
  .event-logo-wrap {{
    display: inline-block;
    vertical-align: middle;
    width: 22px;
    height: 22px;
    margin-right: 8px;
  }}
  .event-logo-img {{
    width: 22px;
    height: 22px;
    object-fit: contain;
    vertical-align: middle;
  }}
  .date-td {{
    font-size: 12px;
    color: #cbd5e1;
    white-space: nowrap;
  }}
  .loc-td {{
    font-size: 12px;
    color: #94a3b8;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .flag-img {{
    width: 17px;
    height: 12px;
    vertical-align: middle;
    margin-right: 6px;
    border-radius: 2px;
    display: inline-block;
  }}
  .prize-td {{
    text-align: right;
    font-size: 12px;
    font-weight: 700;
    color: #fbbf24;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
</style>
</head>
<body>
  <div class="header">
    <div class="header-title">HLTV TOURNAMENTS</div>
    <div class="header-sub">{html.escape(f"{updated_at} · {tier_filter}" if updated_at else tier_filter)}</div>
  </div>
"""
    ]

    if not events_slice:
        empty_title, empty_sub = _events_empty_copy(tier_filter)
        html_parts.append(
            f"""
            <div class="empty-card">
              <div class="empty-title">{html.escape(empty_title)}</div>
              <div class="empty-sub">{html.escape(empty_sub)}</div>
            </div>
            """
        )
    else:
        html_parts.append("""
  <table class="match-table">
    <colgroup>
      <col style="width: 70px;">
      <col style="width: 105px;">
      <col style="width: 325px;">
      <col style="width: 165px;">
      <col style="width: 126px;">
      <col style="width: 125px;">
    </colgroup>
        """)
        for ev in events_slice:
            tier = ev.get("tier") or "T2"
            badge_html = f'<span class="event-tier-badge {tier}">{tier}</span>'
            if ev.get("live"):
                countdown_html = '<span class="live-dot"></span>LIVE'
                cnt_cls = "countdown-td live"
                row_cls = "row live"
            else:
                d = ev.get("days_left", 9999)
                if d == 0:
                    cnt_text = "TODAY"
                elif d == 1:
                    cnt_text = "TOMORROW"
                else:
                    cnt_text = f"IN {d} DAYS"
                countdown_html = html.escape(cnt_text)
                cnt_cls = "countdown-td"
                row_cls = "row"

            date_range = format_event_date_range(ev.get("start_ts") or 0, ev.get("end_ts") or 0)

            raw_loc = ev.get("location") or ""
            cc = ev.get("country_code") or ""
            loc_html = format_location(raw_loc, cc)

            raw_prize = (ev.get("prize") or "").strip()
            if not raw_prize or raw_prize in ("_", "TBA", "Other"):
                prize = "-"
            elif raw_prize.lower().startswith("spots in"):
                # e.g. "Spots in Stage 2" -> "Spots to S2"
                prize = re.sub(r"^spots\s+in\s+", "Spots to ", raw_prize, flags=re.I)
                prize = re.sub(r"\bStage\s+(\d+)\b", r"S\1", prize, flags=re.I)
            else:
                prize = raw_prize
            raw_name = ev.get("name") or "Unknown Event"
            display_name = clean_event_display_name(raw_name)

            # Event logo: cached data uri or local asset fallback or trophy svg
            eid = ev.get("id") or ""
            cached_uri = get_cached_logo_data_uri(eid)
            if cached_uri:
                logo_html = f'<span class="event-logo-wrap"><img class="event-logo-img" src="{cached_uri}" alt="" /></span>'
            else:
                logo_html = _TROPHY_SVG

            html_parts.append(f"""
            <tr class="{row_cls}">
              <td>{badge_html}</td>
              <td class="{cnt_cls}">{countdown_html}</td>
              <td class="event-name-td" title="{html.escape(raw_name)}">{logo_html}{html.escape(display_name)}</td>
              <td class="date-td">{html.escape(date_range)}</td>
              <td class="loc-td">{loc_html}</td>
              <td class="prize-td">{html.escape(prize)}</td>
            </tr>
            """)
        html_parts.append("</table>")

    html_parts.append("</body></html>")
    return "".join(html_parts)


def render_events_image(
    events: Sequence[dict],
    *,
    tier_filter: str = "Major / T1",
    updated_at: str = "",
    limit: int = 15,
) -> bytes:
    """Render events using Python native WeasyPrint (HTML+CSS) with pypdfium2."""
    if weasyprint is None or pypdfium2 is None:
        raise RuntimeError("weasyprint and pypdfium2 are required for HTML/CSS rendering")

    html_content = build_events_html(events, tier_filter=tier_filter, updated_at=updated_at, limit=limit)
    pdf_bytes = weasyprint.HTML(string=html_content).write_pdf()
    doc = pypdfium2.PdfDocument(pdf_bytes)
    page = doc[0]
    pixmap = page.render(scale=1.5)
    pil_image = pixmap.to_pil()

    if ImageChops is not None:
        try:
            bg = Image.new("RGB", pil_image.size, (18, 21, 27))
            diff = ImageChops.difference(pil_image.convert("RGB"), bg)
            bbox = diff.getbbox()
            if bbox and bbox[3] < pil_image.height - 10:
                pil_image = pil_image.crop((0, 0, pil_image.width, min(pil_image.height, bbox[3] + 18)))
        except Exception as e:
            log.debug("events autocrop skipped: %s", e)

    out = io.BytesIO()
    pil_image.save(out, format="PNG")
    return out.getvalue()

