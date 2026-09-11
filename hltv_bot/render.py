from __future__ import annotations

import io
import os
import re
from typing import Sequence

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore

FONT_FALLBACKS = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_FONT_PATH: str | None = None
for p in FONT_FALLBACKS:
    if os.path.exists(p):
        _FONT_PATH = p
        break

_TEAM_CN_MAP = {
    "natus vincere": "NaVi",
    "navi": "NaVi",
    "virtus.pro": "VP",
    "virtus pro": "VP",
    "faze clan": "FaZe",
    "faze": "FaZe",
    "the mongolz": "The MongolZ (蒙古队)",
    "mongolz": "The MongolZ (蒙古队)",
    "rare atom": "Rare Atom (稀有原子)",
    "lyg gaming": "LYG",
    "tyloo": "TYLOO (天禄)",
    "spirit": "Team Spirit (绿龙)",
    "team spirit": "Team Spirit (绿龙)",
    "vitality": "Vitality (小蜜蜂)",
    "team vitality": "Vitality (小蜜蜂)",
    "mouz": "MOUZ (老鼠)",
    "astralis": "Astralis (A队)",
    "complexity": "Complexity (COL)",
    "eternal fire": "Eternal Fire (永恒之火)",
    "heroic": "Heroic",
    "liquid": "Team Liquid (液体)",
    "team liquid": "Team Liquid (液体)",
    "furia": "FURIA (黑豹)",
    "pain gaming": "paiN",
    "pain": "paiN",
    "m80": "M80",
    "imperial": "Imperial (帝国)",
    "big": "BIG",
    "fnatic": "Fnatic",
    "nip": "NIP (忍者)",
    "ninjas in pyjamas": "NIP (忍者)",
    "g2": "G2",
    "g2 esports": "G2",
    "flyquest": "FlyQuest",
}

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
        if re.search(rf"\b{kw}\b", ev):
            return "T3"

    if stars >= 1:
        return "T3"

    return "Other"


def tier_rank(tier: str) -> int:
    return {"T1": 1, "T2": 2, "T3": 3, "Other": 4}.get(tier, 5)


def localize_team(name: str) -> str:
    k = (name or "").strip().lower()
    return _TEAM_CN_MAP.get(k, name)


def _get_font(size: int):
    if _FONT_PATH:
        try:
            return ImageFont.truetype(_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_matches_image(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T3",
    title_suffix: str = "",
) -> bytes:
    """Render matches list into a dark-themed CS2 image."""
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

    if not filtered:
        width = 840
        height = 200
        im = Image.new("RGB", (width, height), (22, 24, 30))
        d = ImageDraw.Draw(im)
        font = _get_font(20)
        d.text((width // 2, height // 2), "当前等级筛选下无比赛", font=font, fill=(180, 180, 180), anchor="mm")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    width = 900
    padding_x = 32
    content_width = width - padding_x * 2

    header_h = 80
    card_h = 72
    card_gap = 10
    legend_h = 45

    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    total_cards = len(filtered)
    tier_headers = len(grouped)
    total_h = (
        header_h
        + tier_headers * 40
        + total_cards * (card_h + card_gap)
        + legend_h
        + 30
    )

    im = Image.new("RGB", (width, total_h), (18, 20, 26))
    d = ImageDraw.Draw(im)

    font_title = _get_font(24)
    font_sub = _get_font(13)
    font_tier = _get_font(16)
    font_team = _get_font(17)
    font_meta = _get_font(13)
    font_time = _get_font(15)
    font_id = _get_font(13)

    # Top accent line
    d.rectangle([(0, 0), (width, 4)], fill=(245, 166, 35))
    d.text((padding_x, 24), "HLTV CS2 今日赛程", font=font_title, fill=(255, 255, 255))
    subtitle = f"默认展示 Tier 3 及以上赛事 · 时间 UTC+8{title_suffix}"
    d.text((padding_x, 54), subtitle, font=font_sub, fill=(140, 145, 160))

    cur_y = header_h + 10
    tier_display_names = {
        "T1": "🔥 Tier 1 / 焦点顶级赛事 (Major, BLAST, IEM, EPL)",
        "T2": "⚡ Tier 2 / 中型巡回赛事 (CCT, ECL, RES)",
        "T3": "🎯 Tier 3 / 预选资格赛与常规赛",
        "Other": "▫️ 其它赛事",
    }
    tier_badge_colors = {
        "T1": (230, 80, 70),
        "T2": (245, 166, 35),
        "T3": (75, 160, 235),
        "Other": (120, 125, 135),
    }

    for t_key in sorted(grouped.keys(), key=tier_rank):
        matches = grouped[t_key]
        d.rectangle([(padding_x, cur_y + 2), (padding_x + 4, cur_y + 18)], fill=tier_badge_colors.get(t_key, (150, 150, 150)))
        d.text((padding_x + 12, cur_y), tier_display_names.get(t_key, t_key), font=font_tier, fill=(220, 225, 235))
        cur_y += 32

        for r in matches:
            live = r.get("live") == "1"
            t1 = localize_team(r.get("team1") or "?")
            t2 = localize_team(r.get("team2") or "?")
            ev = r.get("event") or ""
            clock = r.get("time") or ("LIVE" if live else "")
            stars = int(r.get("stars") or 0)
            mid = r.get("id") or ""

            card_bg = (28, 31, 40) if not live else (38, 28, 32)
            border_color = (48, 52, 66) if not live else (230, 70, 70)
            d.rounded_rectangle(
                [(padding_x, cur_y), (padding_x + content_width, cur_y + card_h)],
                radius=8,
                fill=card_bg,
                outline=border_color,
                width=1 if not live else 2,
            )

            badge_x = padding_x + 16
            if live:
                d.rounded_rectangle(
                    [(badge_x, cur_y + 16), (badge_x + 64, cur_y + 40)],
                    radius=4,
                    fill=(220, 50, 50),
                )
                d.text((badge_x + 32, cur_y + 28), "LIVE", font=font_time, fill=(255, 255, 255), anchor="mm")
            else:
                d.text((badge_x, cur_y + 18), clock or "--:--", font=font_time, fill=(200, 205, 215))

            if stars > 0:
                stars_txt = "★" * stars
                d.text((badge_x, cur_y + 44), stars_txt, font=font_meta, fill=(245, 180, 50))

            teams_x = padding_x + 100
            vs_y = cur_y + 16
            d.text((teams_x, vs_y), f"{t1}  vs  {t2}", font=font_team, fill=(255, 255, 255))

            d.text((teams_x, vs_y + 26), ev[:45], font=font_meta, fill=(140, 145, 160))

            cmd_text = f"/watch {mid}"
            d.text((padding_x + content_width - 16, cur_y + 36), cmd_text, font=font_id, fill=(90, 170, 250), anchor="rm")

            cur_y += card_h + card_gap

        cur_y += 12

    footer_text = "提示: 点击 /watch <id> 可直接开启观赛 · /matches all 查看全部级别赛事"
    d.text((width // 2, cur_y + 10), footer_text, font=font_sub, fill=(110, 115, 130), anchor="mm")

    out = io.BytesIO()
    im.save(out, format="PNG", optimize=True)
    return out.getvalue()
