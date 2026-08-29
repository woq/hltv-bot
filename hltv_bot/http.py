from __future__ import annotations

import logging
from typing import Any

from hltv_bot.debuglog import clip
from hltv_bot.ratelimit import Gap
from hltv_bot.session import BrowserSession

log = logging.getLogger("hltv_bot.http")

# www.hltv.org HTML (list + match page). Not used by scorebot.
_HTML_GAP = Gap()
HTML_MIN_GAP = 3.0


class CloudflareError(RuntimeError):
    def __init__(self, status: int, url: str, hint: str = ""):
        super().__init__(f"Cloudflare {status} on {url} {hint}".strip())
        self.status = status
        self.url = url


def _session_kwargs(sess: BrowserSession, timeout: float) -> dict[str, Any]:
    return {
        "impersonate": sess.impersonate,
        "headers": sess.as_headers(),
        "timeout": timeout,
        "verify": True,
    }


def request(
    sess: BrowserSession,
    method: str,
    url: str,
    *,
    data: bytes | str | None = None,
    timeout: float = 25.0,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    from curl_cffi.requests import Session

    waited = _HTML_GAP.sleep(HTML_MIN_GAP)
    if waited:
        log.debug("html gap slept %.2fs", waited)
    kw = _session_kwargs(sess, timeout)
    extra = dict(kw["headers"])
    if headers:
        extra.update(headers)
    with Session(**{k: v for k, v in kw.items() if k != "headers"}) as client:
        log.debug("http %s %s timeout=%s impersonate=%s", method, url, timeout, sess.impersonate)
        resp = client.request(method, url, data=data, headers=extra)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        log.debug(
            "http %s %s status=%s bytes=%s cf=%s server=%s",
            method,
            url,
            resp.status_code,
            len(resp.content or b""),
            hdrs.get("cf-mitigated") or hdrs.get("cf-ray"),
            hdrs.get("server"),
        )
        if resp.status_code in (403, 429) or hdrs.get("cf-mitigated") == "challenge":
            log.warning(
                "http cloudflare %s %s status=%s hint=%s body=%s",
                method,
                url,
                resp.status_code,
                hdrs.get("cf-mitigated", ""),
                clip((resp.content or b"")[:300], 300),
            )
            raise CloudflareError(resp.status_code, url, hdrs.get("cf-mitigated", ""))
        return resp.status_code, resp.content, hdrs
