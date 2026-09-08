from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hltv_bot.profile import DEFAULT_UA, build_headers, pick_impersonate

# Scorebot Set-Cookie 只轮换这些；其它（OptanonConsent 等）保留 Chrome 粘贴原样。
_ROTATE_COOKIE_KEYS = frozenset(("io", "_cfuvid", "__cflb", "cf_clearance", "__cf_bm"))


def _cookie_value_ok(value: str) -> bool:
    if not value or "\r" in value or "\n" in value or "\0" in value:
        return False
    try:
        value.encode("latin-1")
    except UnicodeEncodeError:
        return False
    return True


def _pairs_from_cookie_str(text: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in (text or "").split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and _cookie_value_ok(v):
            pairs[k] = v
    return pairs


def _pairs_from_jar(src: object) -> dict[str, str]:
    out: dict[str, str] = {}
    items = getattr(src, "items", None)
    if not callable(items):
        return out
    try:
        iterator = items()
    except Exception:
        return out
    for k, v in iterator:
        name = str(k).strip()
        if name not in _ROTATE_COOKIE_KEYS:
            continue
        val = v if isinstance(v, str) else getattr(v, "value", None)
        if val is None:
            val = str(v)
        val = str(val).strip()
        if name and _cookie_value_ok(val):
            out[name] = val
    return out


@dataclass
class BrowserSession:
    impersonate: str
    headers: dict[str, str]
    cookie: str
    path: Path | None = None

    def cookie_names(self) -> list[str]:
        names = []
        for part in self.cookie.split(";"):
            part = part.strip()
            if "=" in part:
                names.append(part.split("=", 1)[0])
        return names

    def has_clearance(self) -> bool:
        names = set(self.cookie_names())
        return "cf_clearance" in names

    def as_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = dict(self.headers)
        cookie = format_cookie_header(_pairs_from_cookie_str(self.cookie))
        if cookie:
            h["cookie"] = cookie
        if extra:
            h.update(extra)
        return h

    def update_cookie(self, new_pairs: dict[str, str] | str) -> None:
        """Merge incoming cookies (e.g. fresh __cf_bm from Set-Cookie) and persist."""
        if not new_pairs:
            return
        current = parse_session_paste(self.cookie).get("cookie", "")
        pairs = _pairs_from_cookie_str(current)
        if isinstance(new_pairs, str):
            pairs.update(_pairs_from_cookie_str(new_pairs))
        elif hasattr(new_pairs, "items"):
            pairs.update(_pairs_from_jar(new_pairs))
        new_cookie_str = format_cookie_header(pairs)
        if new_cookie_str != self.cookie:
            self.cookie = new_cookie_str
            if "cookie" in self.headers:
                self.headers["cookie"] = new_cookie_str
            if self.path and self.path.exists():
                try:
                    save_cookie(self.path, new_cookie_str)
                except Exception:
                    pass


def format_cookie_header(pairs: dict[str, str]) -> str:
    first_keys = ("io", "_cfuvid", "__cflb", "cf_clearance", "__cf_bm")
    seen: set[str] = set()
    merged: list[str] = []
    for fk in first_keys:
        if fk in pairs and _cookie_value_ok(pairs[fk]):
            merged.append(f"{fk}={pairs[fk]}")
            seen.add(fk)
    for k, v in pairs.items():
        if k and k not in seen and _cookie_value_ok(v):
            merged.append(f"{k}={v}")
            seen.add(k)
    return "; ".join(merged)


_SESSION_KEYS = (
    "impersonate",
    "user_agent",
    "sec_ch_ua",
    "sec_ch_ua_mobile",
    "sec_ch_ua_platform",
    "accept_language",
    "dnt",
    "cookie",
)


def parse_session_paste(raw: str) -> dict:
    """Cookie header, or a full session.json object."""
    text = (raw or "").strip()
    if text.startswith("{") and "cookie" in text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and "cookie" in data:
            out = {}
            for k in _SESSION_KEYS:
                if k in data and data[k] is not None:
                    out[k] = data[k]
            out["cookie"] = parse_cookie_line(str(out.get("cookie") or ""))
            return out
    return {"cookie": parse_cookie_line(text)}


def parse_cookie_line(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("{") and "cookie" in text:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("cookie") is not None:
            text = str(data.get("cookie") or "")
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    return text


def load_session(path: str | Path) -> BrowserSession:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    cookie = format_cookie_header(_pairs_from_cookie_str(parse_cookie_line(data.get("cookie") or "")))
    headers = build_headers(
        user_agent=data.get("user_agent") or DEFAULT_UA,
        sec_ch_ua=data.get("sec_ch_ua") or build_headers()["sec-ch-ua"],
        sec_ch_ua_mobile=data.get("sec_ch_ua_mobile") or "?0",
        sec_ch_ua_platform=data.get("sec_ch_ua_platform") or '"Windows"',
        accept_language=data.get("accept_language") or "zh-CN,zh;q=0.9,zh-TW;q=0.8",
        dnt=str(data.get("dnt") or "1"),
    )
    return BrowserSession(
        impersonate=pick_impersonate(data.get("impersonate")),
        headers=headers,
        cookie=cookie,
        path=p,
    )


def save_cookie(path: str | Path, cookie: str) -> None:
    p = Path(path)
    if p.exists():
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        data = json.loads(
            Path(__file__).resolve().parents[1].joinpath("data/session.example.json").read_text(
                encoding="utf-8"
            )
        )
    patch = parse_session_paste(cookie)
    for k, v in patch.items():
        if k in _SESSION_KEYS and v is not None:
            data[k] = v
    data["cookie"] = parse_cookie_line(str(data.get("cookie") or ""))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
