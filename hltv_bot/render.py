from __future__ import annotations

import html
import io
import json
import logging
import os
import re
from typing import Sequence

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore

try:
    import resvg
except ImportError:
    resvg = None

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


def _get_team_svg_inner(name: str) -> str | None:
    norm = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    logo_dir = os.path.join(os.path.dirname(__file__), "assets", "logos")
    svg_path = os.path.join(logo_dir, f"{norm}.svg")
    if os.path.exists(svg_path):
        try:
            with open(svg_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                m = re.search(r"<svg[^>]*>(.*)</svg>", content, re.DOTALL | re.IGNORECASE)
                if m:
                    return m.group(1).strip()
        except Exception:
            pass
    return None


def generate_matches_svg(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    updated_at: str = "",
) -> str:
    """Generate high-precision, modern SVG markup for match list."""
    max_rank = tier_rank(tier_filter)
    filtered = []
    for r in rows:
        stars = int(r.get("stars") or 0)
        t = classify_event_tier(r.get("event") or "", stars)
        r_copy = dict(r)
        r_copy["_tier"] = t
        if tier_rank(t) <= max_rank:
            filtered.append(r_copy)

    width = 480
    header_h = 46
    card_h = 32
    card_gap = 4

    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    tier_meta = {
        "T1": ("TIER 1 / MAJOR & BIG EVENTS", "#f87171"),
        "T2": ("TIER 2 / CHALLENGER & CIRCUIT", "#fbbf24"),
        "T3": ("TIER 3 / QUALIFIERS & CUPS", "#60a5fa"),
        "Other": ("OTHER MATCHES", "#94a3b8"),
    }

    if not filtered:
        h = 120
        return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" viewBox="0 0 {width} {h}">
  <rect width="{width}" height="{h}" rx="8" fill="#12151b"/>
  <text x="{width // 2}" y="65" fill="#64748b" font-family="DejaVu Sans, Arial, sans-serif" font-size="13" font-weight="500" text-anchor="middle">No matches found for {html.escape(tier_filter)}</text>
</svg>"""

    total_h = header_h + len(grouped) * 26 + len(filtered) * (card_h + card_gap) + 30

    svg_parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{total_h}" viewBox="0 0 {width} {total_h}">',
        '  <defs>',
        '    <linearGradient id="bgGrad" x1="0%" y1="0%" x2="0%" y2="100%">',
        '      <stop offset="0%" stop-color="#151922"/>',
        '      <stop offset="100%" stop-color="#0f1217"/>',
        '    </linearGradient>',
        '  </defs>',
        f'  <rect width="{width}" height="{total_h}" fill="url(#bgGrad)"/>',
        f'  <text x="16" y="27" fill="#ffffff" font-family="DejaVu Sans, Arial, sans-serif" font-size="14" font-weight="700" letter-spacing="0.5">HLTV MATCHES</text>',
    ]

    header_sub = f"{updated_at} · {tier_filter}" if updated_at else tier_filter
    svg_parts.append(
        f'  <text x="{width - 16}" y="27" fill="#64748b" font-family="DejaVu Sans, Arial, sans-serif" font-size="11" font-weight="500" text-anchor="end">{html.escape(header_sub)}</text>'
    )
    svg_parts.append(f'  <line x1="16" y1="38" x2="{width - 16}" y2="38" stroke="#232936" stroke-width="1.5"/>')

    cur_y = header_h

    for t in sorted(grouped.keys(), key=tier_rank):
        label, color = tier_meta.get(t, (f"── {t} ──", "#94a3b8"))
        svg_parts.append(
            f'  <circle cx="21" cy="{cur_y + 11}" r="3" fill="{color}"/>'
        )
        svg_parts.append(
            f'  <text x="30" y="{cur_y + 15}" fill="{color}" font-family="DejaVu Sans, Arial, sans-serif" font-size="10" font-weight="700" letter-spacing="0.5">{html.escape(label)}</text>'
        )
        cur_y += 24

        for m in grouped[t]:
            live = m.get("live") == "1"
            bg = "#22161b" if live else "#181d26"
            border = "#ef4444" if live else "#232a38"
            svg_parts.append(
                f'  <rect x="16" y="{cur_y}" width="{width - 32}" height="{card_h}" rx="5" fill="{bg}" stroke="{border}" stroke-width="1"/>'
            )

            # Time / LIVE Badge
            if live:
                svg_parts.append(
                    f'  <circle cx="26" cy="{cur_y + 16}" r="3.5" fill="#ef4444"/>'
                )
                svg_parts.append(
                    f'  <text x="34" y="{cur_y + 20}" fill="#f87171" font-family="DejaVu Sans, Arial, sans-serif" font-size="11" font-weight="700">LIVE</text>'
                )
            else:
                clock = m.get("time") or "--:--"
                svg_parts.append(
                    f'  <text x="24" y="{cur_y + 20}" fill="#94a3b8" font-family="DejaVu Sans, Arial, sans-serif" font-size="11" font-weight="600">{html.escape(clock)}</text>'
                )

            # Team 1
            t1 = m.get("team1") or "?"
            t1_initials = _get_initials(t1)
            t1_bg, t1_fg = _get_badge_style(t1)
            t1_svg = _get_team_svg_inner(t1)

            t1_badge_x = 76
            t1_badge_y = cur_y + 8
            if t1_svg:
                svg_parts.append(
                    f'  <g transform="translate({t1_badge_x}, {t1_badge_y}) scale(0.5)">{t1_svg}</g>'
                )
            else:
                svg_parts.append(
                    f'  <rect x="{t1_badge_x}" y="{t1_badge_y}" width="16" height="15" rx="3" fill="{t1_bg}"/>'
                )
                svg_parts.append(
                    f'  <text x="{t1_badge_x + 8}" y="{t1_badge_y + 11}" fill="{t1_fg}" font-family="DejaVu Sans, monospace" font-size="8" font-weight="700" text-anchor="middle">{html.escape(t1_initials)}</text>'
                )

            # Team 1 text
            t1_name_esc = html.escape(t1[:12])
            svg_parts.append(
                f'  <text x="98" y="{cur_y + 20}" fill="#ffffff" font-family="DejaVu Sans, Arial, sans-serif" font-size="12" font-weight="600">{t1_name_esc}</text>'
            )

            # "vs"
            svg_parts.append(
                f'  <text x="190" y="{cur_y + 20}" fill="#475569" font-family="DejaVu Sans, Arial, sans-serif" font-size="10" font-weight="600" text-anchor="middle">vs</text>'
            )

            # Team 2
            t2 = m.get("team2") or "?"
            t2_initials = _get_initials(t2)
            t2_bg, t2_fg = _get_badge_style(t2)
            t2_svg = _get_team_svg_inner(t2)

            t2_badge_x = 208
            t2_badge_y = cur_y + 8
            if t2_svg:
                svg_parts.append(
                    f'  <g transform="translate({t2_badge_x}, {t2_badge_y}) scale(0.5)">{t2_svg}</g>'
                )
            else:
                svg_parts.append(
                    f'  <rect x="{t2_badge_x}" y="{t2_badge_y}" width="16" height="15" rx="3" fill="{t2_bg}"/>'
                )
                svg_parts.append(
                    f'  <text x="{t2_badge_x + 8}" y="{t2_badge_y + 11}" fill="{t2_fg}" font-family="DejaVu Sans, monospace" font-size="8" font-weight="700" text-anchor="middle">{html.escape(t2_initials)}</text>'
                )

            # Team 2 text
            t2_name_esc = html.escape(t2[:12])
            svg_parts.append(
                f'  <text x="230" y="{cur_y + 20}" fill="#ffffff" font-family="DejaVu Sans, Arial, sans-serif" font-size="12" font-weight="600">{t2_name_esc}</text>'
            )

            # Stars (render crisp gold star path)
            stars = int(m.get("stars") or 0)
            if stars > 0:
                for s_idx in range(stars):
                    sx = width - 88 - (stars - 1 - s_idx) * 11
                    sy = cur_y + 11
                    svg_parts.append(
                        f'  <polygon points="{sx+5},{sy} {sx+6.5},{sy+3.5} {sx+10},{sy+4} {sx+7.5},{sy+6.5} {sx+8},{sy+10} {sx+5},{sy+8} {sx+2},{sy+10} {sx+2.5},{sy+6.5} {sx},{sy+4} {sx+3.5},{sy+3.5}" fill="#f59e0b"/>'
                    )

            # Match ID
            mid = m.get("id") or ""
            svg_parts.append(
                f'  <text x="{width - 24}" y="{cur_y + 20}" fill="#38bdf8" font-family="DejaVu Sans, monospace" font-size="11" font-weight="600" text-anchor="end">#{mid}</text>'
            )

            cur_y += card_h + card_gap
        cur_y += 6

    # Footer
    svg_parts.append(
        f'  <text x="{width // 2}" y="{cur_y + 10}" fill="#475569" font-family="DejaVu Sans, Arial, sans-serif" font-size="10" font-weight="500" text-anchor="middle">/watch &lt;id&gt; to stream live scorebot</text>'
    )
    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


def _load_fallback_font(size: int, bold: bool = False):
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def render_matches_image_fallback(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    updated_at: str = "",
) -> bytes:
    """Compact Pillow fallback if resvg is unavailable."""
    if Image is None:
        raise RuntimeError("Pillow is not installed")

    max_rank = tier_rank(tier_filter)
    filtered = []
    for r in rows:
        stars = int(r.get("stars") or 0)
        t = classify_event_tier(r.get("event") or "", stars)
        r_copy = dict(r)
        r_copy["_tier"] = t
        if tier_rank(t) <= max_rank:
            filtered.append(r_copy)

    width = 480
    f_title = _load_fallback_font(14, bold=True)
    f_sub = _load_fallback_font(11)
    f_tier = _load_fallback_font(10, bold=True)
    f_time = _load_fallback_font(11, bold=True)
    f_team = _load_fallback_font(12, bold=True)
    f_meta = _load_fallback_font(10)
    f_id = _load_fallback_font(11)

    if not filtered:
        im = Image.new("RGB", (width, 120), (18, 21, 27))
        d = ImageDraw.Draw(im)
        d.text((width // 2, 60), f"No matches found for {tier_filter}", font=f_sub, fill=(148, 163, 184), anchor="mm")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    card_h = 30
    card_gap = 4
    header_h = 46
    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    tier_labels = {
        "T1": ("• TIER 1 / MAJOR & BIG EVENTS", (248, 113, 113)),
        "T2": ("• TIER 2 / CHALLENGER & CIRCUIT", (251, 191, 36)),
        "T3": ("• TIER 3 / QUALIFIERS & CUPS", (96, 165, 250)),
        "Other": ("• OTHER MATCHES", (148, 163, 184)),
    }

    total_h = header_h + len(grouped) * 26 + len(filtered) * (card_h + card_gap) + 26
    im = Image.new("RGB", (width, total_h), (18, 21, 27))
    d = ImageDraw.Draw(im)

    # Header
    d.text((14, 14), "HLTV MATCHES", font=f_title, fill=(255, 255, 255))
    header_sub_text = f"{updated_at} · {tier_filter}" if updated_at else tier_filter
    d.text((width - 14, 16), header_sub_text, font=f_sub, fill=(100, 116, 139), anchor="ra")
    d.line([(14, 38), (width - 14, 38)], fill=(35, 41, 54), width=2)

    cur_y = header_h

    for t in sorted(grouped.keys(), key=tier_rank):
        label, col = tier_labels.get(t, (f"── {t} ──", (148, 163, 184)))
        d.text((14, cur_y), label, font=f_tier, fill=col)
        cur_y += 20

        for m in grouped[t]:
            live = m.get("live") == "1"
            bg = (35, 22, 26) if live else (25, 30, 39)
            border = (239, 68, 68) if live else (35, 42, 54)
            d.rounded_rectangle([(14, cur_y), (width - 14, cur_y + card_h)], radius=4, fill=bg, outline=border, width=1)

            # Time / Status
            t_col = (248, 113, 113) if live else (148, 163, 184)
            time_txt = "LIVE" if live else (m.get("time") or "--:--")
            d.text((22, cur_y + 8), time_txt, font=f_time, fill=t_col)

            # Teams
            t1 = m.get("team1") or "?"
            t2 = m.get("team2") or "?"
            d.text((82, cur_y + 7), t1, font=f_team, fill=(255, 255, 255))
            vs_x = 82 + int(d.textlength(t1, font=f_team)) + 6
            d.text((vs_x, cur_y + 8), "vs", font=f_meta, fill=(71, 85, 105))
            t2_x = vs_x + int(d.textlength("vs", font=f_meta)) + 6
            d.text((t2_x, cur_y + 7), t2, font=f_team, fill=(255, 255, 255))

            # Stars
            stars = int(m.get("stars") or 0)
            if stars > 0:
                stars_x = t2_x + int(d.textlength(t2, font=f_team)) + 8
                d.text((stars_x, cur_y + 8), "★" * stars, font=f_meta, fill=(245, 158, 11))

            # ID
            d.text((width - 22, cur_y + 8), f"#{m.get('id')}", font=f_id, fill=(56, 189, 248), anchor="ra")
            cur_y += card_h + card_gap
        cur_y += 6

    # Footer
    d.text((width // 2, cur_y + 4), "/watch <id> to stream live scorebot", font=f_meta, fill=(71, 85, 105), anchor="mm")

    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def render_matches_image(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    title_suffix: str = "",
    updated_at: str = "",
) -> bytes:
    """Render matches using pure Python resvg (with Pillow fallback). No Chrome/Node needed."""
    if resvg is not None:
        try:
            svg_content = generate_matches_svg(rows, tier_filter=tier_filter, updated_at=updated_at)
            opt = resvg.usvg.Options.default()
            opt.load_system_fonts()
            tree = resvg.usvg.Tree.from_str(svg_content, opt)
            data = resvg.render(tree, (1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
            if data:
                return data
        except Exception as e:
            log.warning("resvg render failed, falling back to pillow: %s", e)

    return render_matches_image_fallback(rows, tier_filter=tier_filter, updated_at=updated_at)
