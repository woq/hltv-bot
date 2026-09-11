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
    tier_filter: str = "T3",
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

    payload = json.dumps({"matches": data, "tier_filter": tier_filter}).encode("utf-8")

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


def render_matches_image_fallback(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T3",
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

    width = 440
    if not filtered:
        im = Image.new("RGB", (width, 120), (20, 23, 30))
        d = ImageDraw.Draw(im)
        f = ImageFont.load_default()
        d.text((width // 2, 60), f"No matches found for {tier_filter}", font=f, fill=(160, 160, 160), anchor="mm")
        out = io.BytesIO()
        im.save(out, format="PNG")
        return out.getvalue()

    card_h = 28
    card_gap = 4
    header_h = 44
    grouped: dict[str, list[dict]] = {}
    for r in filtered:
        grouped.setdefault(r["_tier"], []).append(r)

    total_h = header_h + len(grouped) * 24 + len(filtered) * (card_h + card_gap) + 20
    im = Image.new("RGB", (width, total_h), (20, 23, 30))
    d = ImageDraw.Draw(im)
    f = ImageFont.load_default()

    d.text((14, 16), f"HLTV MATCHES · {tier_filter}", font=f, fill=(255, 255, 255))
    cur_y = header_h

    for t in sorted(grouped.keys(), key=tier_rank):
        d.text((14, cur_y), f"── {t} ──", font=f, fill=(160, 174, 192))
        cur_y += 20
        for m in grouped[t]:
            live = m.get("live") == "1"
            bg = (37, 27, 32) if live else (30, 35, 45)
            d.rectangle([(14, cur_y), (width - 14, cur_y + card_h)], fill=bg)
            t_col = (255, 100, 100) if live else (180, 190, 205)
            d.text((20, cur_y + 8), "LIVE" if live else (m.get("time") or "--:--"), font=f, fill=t_col)
            vs = f"{m.get('team1') or '?'} vs {m.get('team2') or '?'}"
            d.text((75, cur_y + 8), vs[:32], font=f, fill=(255, 255, 255))
            d.text((width - 20, cur_y + 8), f"#{m.get('id')}", font=f, fill=(99, 179, 237), anchor="ra")
            cur_y += card_h + card_gap
        cur_y += 6

    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def render_matches_image(
    rows: Sequence[dict],
    *,
    tier_filter: str = "T3",
    title_suffix: str = "",
) -> bytes:
    """Render matches using Puppeteer with pure Python fallback."""
    try:
        return render_matches_puppeteer(rows, tier_filter=tier_filter)
    except Exception as e:
        log.warning("Puppeteer render failed, falling back to compact pillow: %s", e)
        return render_matches_image_fallback(rows, tier_filter=tier_filter)
