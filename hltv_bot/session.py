from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from hltv_bot.profile import DEFAULT_UA, build_headers, pick_impersonate


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
        if self.cookie:
            h["cookie"] = self.cookie
        if extra:
            h.update(extra)
        return h


def parse_cookie_line(raw: str) -> str:
    text = raw.strip()
    if text.lower().startswith("cookie:"):
        text = text.split(":", 1)[1].strip()
    return text


def load_session(path: str | Path) -> BrowserSession:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    cookie = parse_cookie_line(data.get("cookie") or "")
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
    data["cookie"] = parse_cookie_line(cookie)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
