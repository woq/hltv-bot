from __future__ import annotations

from typing import Any

from hltv_bot.session import BrowserSession


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

    kw = _session_kwargs(sess, timeout)
    extra = dict(kw["headers"])
    if headers:
        extra.update(headers)
    with Session(**{k: v for k, v in kw.items() if k != "headers"}) as client:
        resp = client.request(method, url, data=data, headers=extra)
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        if resp.status_code in (403, 429) or hdrs.get("cf-mitigated") == "challenge":
            raise CloudflareError(resp.status_code, url, hdrs.get("cf-mitigated", ""))
        return resp.status_code, resp.content, hdrs
