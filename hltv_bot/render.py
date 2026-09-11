from __future__ import annotations

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
    ((43, 57, 69), (144, 205, 244)),   # Blue
    ((59, 47, 69), (214, 188, 250)),   # Purple
    ((47, 62, 53), (154, 230, 180)),   # Green
    ((69, 56, 43), (251, 211, 141)),   # Orange
    ((69, 43, 43), (254, 178, 178)),   # Red
    ((43, 63, 62), (129, 230, 217)),   # Teal
]


def _get_badge_style(name: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
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


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
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


def render_matches_image(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    title_suffix: str = "",
    updated_at: str = "",
) -> bytes:
    """Crisp, high-fidelity match card rendered with pure Pillow (no Chrome/Node)."""
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
    f_title = _load_font(13, bold=True)
    f_sub = _load_font(10)
    f_tier = _load_font(10, bold=True)
    f_time = _load_font(10, bold=True)
    f_team = _load_font(11, bold=True)
    f_meta = _load_font(9)
    f_badge = _load_font(8, bold=True)
    f_id = _load_font(10, bold=True)

    if not filtered:
        im = Image.new("RGB", (width, 100), (18, 21, 27))
        d = ImageDraw.Draw(im)
        d.text((width // 2, 50), f"No matches found for {tier_filter}", font=f_sub, fill=(148, 163, 184), anchor="mm")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    card_h = 32
    card_gap = 5
    header_h = 44
    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    tier_labels = {
        "T1": ("TIER 1 / MAJOR & BIG EVENTS", (248, 113, 113)),
        "T2": ("TIER 2 / CHALLENGER & CIRCUIT", (251, 191, 36)),
        "T3": ("TIER 3 / QUALIFIERS & CUPS", (96, 165, 250)),
        "Other": ("OTHER MATCHES", (148, 163, 184)),
    }

    total_h = header_h + len(grouped) * 26 + len(filtered) * (card_h + card_gap) + 24
    im = Image.new("RGB", (width, total_h), (18, 21, 27))
    d = ImageDraw.Draw(im)

    # Top Header
    d.text((16, 15), "HLTV MATCHES", font=f_title, fill=(255, 255, 255))
    header_sub_text = f"{updated_at} · {tier_filter}" if updated_at else tier_filter
    d.text((width - 16, 17), header_sub_text, font=f_sub, fill=(100, 116, 139), anchor="ra")
    d.line([(16, 36), (width - 16, 36)], fill=(35, 41, 54), width=1)

    cur_y = header_h

    for t in sorted(grouped.keys(), key=tier_rank):
        label, col = tier_labels.get(t, (f"── {t} ──", (148, 163, 184)))
        # Bullet dot
        d.ellipse([(16, cur_y + 4), (22, cur_y + 10)], fill=col)
        d.text((26, cur_y + 2), label, font=f_tier, fill=col)
        cur_y += 22

        for m in grouped[t]:
            live = m.get("live") == "1"
            bg = (34, 22, 27) if live else (24, 29, 38)
            border = (239, 68, 68) if live else (35, 42, 56)
            d.rounded_rectangle([(16, cur_y), (width - 16, cur_y + card_h)], radius=5, fill=bg, outline=border, width=1)

            # Time / Status
            if live:
                d.ellipse([(24, cur_y + 13), (29, cur_y + 18)], fill=(239, 68, 68))
                d.text((32, cur_y + 9), "LIVE", font=f_time, fill=(248, 113, 113))
            else:
                clock = m.get("time") or "--:--"
                d.text((24, cur_y + 9), clock, font=f_time, fill=(148, 163, 184))

            # Team 1 Badge & Text
            t1 = m.get("team1") or "?"
            t1_bg, t1_fg = _get_badge_style(t1)
            d.rounded_rectangle([(74, cur_y + 8), (90, cur_y + 23)], radius=3, fill=t1_bg)
            d.text((82, cur_y + 15), _get_initials(t1), font=f_badge, fill=t1_fg, anchor="mm")
            d.text((95, cur_y + 9), t1[:11], font=f_team, fill=(255, 255, 255))

            # vs
            d.text((188, cur_y + 10), "vs", font=f_meta, fill=(71, 85, 105), anchor="mm")

            # Team 2 Badge & Text
            t2 = m.get("team2") or "?"
            t2_bg, t2_fg = _get_badge_style(t2)
            d.rounded_rectangle([(200, cur_y + 8), (216, cur_y + 23)], radius=3, fill=t2_bg)
            d.text((208, cur_y + 15), _get_initials(t2), font=f_badge, fill=t2_fg, anchor="mm")
            d.text((221, cur_y + 9), t2[:11], font=f_team, fill=(255, 255, 255))

            # Stars
            stars = int(m.get("stars") or 0)
            if stars > 0:
                stars_txt = "★" * stars
                d.text((width - 86, cur_y + 9), stars_txt, font=f_meta, fill=(245, 158, 11), anchor="ra")

            # Match ID
            d.text((width - 24, cur_y + 9), f"#{m.get('id')}", font=f_id, fill=(56, 189, 248), anchor="ra")

            cur_y += card_h + card_gap
        cur_y += 5

    # Footer
    d.text((width // 2, cur_y + 6), "/watch <id> to stream live scorebot", font=f_meta, fill=(71, 85, 105), anchor="mm")

    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()
