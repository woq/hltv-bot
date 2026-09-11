from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
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
        if re.search(rf"\b{kw}\b", ev):
            return "T3"

    if stars >= 1:
        return "T3"

    return "Other"


def tier_rank(tier: str) -> int:
    return {"T1": 1, "T2": 2, "T3": 3, "Other": 4}.get(tier, 5)


def localize_team(name: str) -> str:
    # Retain clean English name directly without verbose chinese
    return name


def _find_node_bin() -> str | None:
    p = shutil.which("node")
    if p:
        return p
    candidates = [
        "/home/x/.local/share/fnm/node-versions/v24.16.0/installation/bin/node",
        "/usr/local/bin/node",
        "/usr/bin/node",
    ]
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def render_matches_puppeteer(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T2",
    updated_at: str = "",
) -> bytes:
    node_bin = _find_node_bin()
    if not node_bin:
        raise RuntimeError("Node binary not found")

    script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "render_matches.js")
    if not os.path.exists(script_path):
        raise RuntimeError(f"render_matches.js not found at {script_path}")

    # Prepare data
    data = []
    for r in rows:
        c = dict(r)
        c["_tier"] = classify_event_tier(r.get("event") or "", int(r.get("stars") or 0))
        data.append(c)

    payload = json.dumps({
        "matches": data,
        "tier_filter": tier_filter,
        "updated_at": updated_at,
    }).encode("utf-8")

    env = os.environ.copy()
    node_dir = os.path.dirname(node_bin)
    env["PATH"] = f"{node_dir}:{env.get('PATH', '')}"
    node_modules = "/home/x/.local/share/fnm/node-versions/v24.16.0/installation/lib/node_modules"
    if os.path.exists(node_modules):
        env["NODE_PATH"] = node_modules

    res = subprocess.run(
        [node_bin, script_path],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=15.0,
    )

    if res.returncode != 0:
        err_msg = res.stderr.decode("utf-8", "replace")[:300]
        raise RuntimeError(f"Puppeteer failed (code {res.returncode}): {err_msg}")

    return res.stdout


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
    """Compact Pillow fallback if puppeteer is unavailable."""
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
        "T1": ("🔥 TIER 1 / MAJOR & BIG EVENTS", (248, 113, 113)),
        "T2": ("⚡ TIER 2 / CHALLENGER & CIRCUIT", (251, 191, 36)),
        "T3": ("🎯 TIER 3 / QUALIFIERS & CUPS", (96, 165, 250)),
        "Other": ("▫️ OTHER MATCHES", (148, 163, 184)),
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
            time_txt = "🔴 LIVE" if live else (m.get("time") or "--:--")
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
    """Render matches using Puppeteer with pure Python fallback."""
    try:
        return render_matches_puppeteer(rows, tier_filter=tier_filter, updated_at=updated_at)
    except Exception as e:
        log.warning("Puppeteer render failed, falling back to compact pillow: %s", e)
        return render_matches_image_fallback(rows, tier_filter=tier_filter, updated_at=updated_at)
