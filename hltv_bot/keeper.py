from __future__ import annotations

import html
import logging
import threading
import time
from typing import Any

from hltv_bot.cdp import CdpUnavailable, DEFAULT_CDP, KEEPER_URL, fetch_keeper_snapshot
from hltv_bot.session import is_challenge_cdp

log = logging.getLogger("hltv_bot.keeper")

CDP_EXPORT_EVERY = 300.0
ADMIN_CHALLENGE_EVERY = 1800.0
ADMIN_CDP_DOWN_EVERY = 1800.0


def cdp_url_from_env(raw: str | None) -> str | None:
    """Unset → default attach URL. Explicit off → None (no keeper thread)."""
    if raw is None:
        return DEFAULT_CDP
    text = raw.strip()
    if text.lower() in {"", "0", "off", "disable", "false", "no"}:
        return None
    return text


def export_every_from_env(raw: str | None) -> float:
    try:
        val = float(raw) if raw not in (None, "") else CDP_EXPORT_EVERY
    except (TypeError, ValueError):
        val = CDP_EXPORT_EVERY
    return max(60.0, val)


def _alert_challenge(bot: Any, snap: Any) -> None:
    clearance = "NO"
    title = html.escape(snap.title or "")
    tab = html.escape(snap.url or "")
    caption = (
        f"<b>HLTV Chrome keeper: challenge</b>\n"
        f"title=<code>{title}</code>\n"
        f"cf_clearance={clearance}\n"
        f"tab=<code>{tab}</code>"
    )
    body = (
        caption
        + "\nDo not restart Chrome. SSH tunnel noVNC, pass Turnstile, then wait for next export.\n"
        "<code>ssh -L 6080:127.0.0.1:6080 root@191.96.243.105</code>"
    )
    if snap.screenshot_png:
        bot._notify_admins_photo(snap.screenshot_png, caption=caption, filename="cf-challenge.png")
    bot._notify_admins(body)


def tick_keeper(bot: Any, *, sleep: Any = None) -> None:
    sleeper = time.sleep if sleep is None else sleep
    url = bot.cdp_url or DEFAULT_CDP
    keeper_url = getattr(bot, "keeper_url", None) or KEEPER_URL
    snap = fetch_keeper_snapshot(url, keeper_url=keeper_url)
    if snap.created_new_tab and not (snap.title or "").strip():
        sleeper(15.0)
        snap = fetch_keeper_snapshot(url, keeper_url=keeper_url)
    bot.keeper_title = snap.title
    bot.keeper_url_seen = snap.url
    challenge = is_challenge_cdp(snap.title, snap.url, snap.cookies)
    bot.keeper_clearance = (not challenge) and bot.session.has_clearance()
    if challenge:
        bot.keeper_cdp = "up"
        now = time.monotonic()
        last = float(getattr(bot, "_challenge_alerted_at", 0.0) or 0.0)
        if last <= 0 or (now - last) >= ADMIN_CHALLENGE_EVERY:
            _alert_challenge(bot, snap)
            bot._challenge_alerted_at = now
        bot._was_challenge = True
        log.warning("keeper challenge title=%s", snap.title)
        return
    changed = bot.session.overlay_cdp(snap.cookies)
    bot.keeper_cdp = "up"
    bot.keeper_exported_at = time.monotonic()
    bot.keeper_clearance = bot.session.has_clearance()
    log.info(
        "keeper export clearance=%s changed=%s title=%s",
        "yes" if bot.keeper_clearance else "NO",
        changed,
        snap.title,
    )
    if getattr(bot, "_was_challenge", False):
        bot._notify_admins("<b>HLTV Chrome keeper: clearance restored</b>")
        bot._was_challenge = False
        bot._challenge_alerted_at = 0.0


def _loop(bot: Any) -> None:
    stop: threading.Event = bot._keeper_stop
    every = float(bot.export_every or CDP_EXPORT_EVERY)
    while not stop.is_set():
        quick = False
        try:
            tick_keeper(bot)
            bot._cdp_down_alerted_at = 0.0
        except CdpUnavailable as e:
            bot.keeper_cdp = "down"
            log.warning("keeper cdp down: %s", e)
            now = time.monotonic()
            last = float(getattr(bot, "_cdp_down_alerted_at", 0.0) or 0.0)
            if last <= 0 or (now - last) >= ADMIN_CDP_DOWN_EVERY:
                bot._notify_admins(
                    "<b>HLTV Chrome keeper: cdp down</b>\n"
                    "Chrome Restart=no. <code>systemctl start xvfb@99 hltv-chrome</code> "
                    "then SSH tunnel 6080 and pass Turnstile.\n"
                    f"<code>{html.escape(str(e)[:200])}</code>"
                )
                bot._cdp_down_alerted_at = now
            quick = True
        except Exception:
            log.exception("keeper tick")
            bot.keeper_cdp = "down"
            now = time.monotonic()
            last = float(getattr(bot, "_cdp_down_alerted_at", 0.0) or 0.0)
            if last <= 0 or (now - last) >= ADMIN_CDP_DOWN_EVERY:
                bot._notify_admins("<b>HLTV Chrome keeper: cdp down</b>\nkeeper tick failed")
                bot._cdp_down_alerted_at = now
            quick = True
        stop.wait(15.0 if quick else every)


def start_keeper_thread(bot: Any) -> threading.Thread | None:
    if not bot.cdp_url:
        log.info("keeper disabled")
        return None
    bot._keeper_stop = getattr(bot, "_keeper_stop", None) or threading.Event()
    t = threading.Thread(target=_loop, args=(bot,), daemon=True, name="hltv-keeper")
    t.start()
    bot._keeper_thread = t
    log.info("keeper thread started cdp=%s every=%s", bot.cdp_url, bot.export_every)
    return t
