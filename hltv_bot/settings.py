from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

DEFAULT_PATH = Path("data/settings.json")
_lock = Lock()


def load_settings(path: Path = DEFAULT_PATH) -> dict:
    if not path.exists():
        return {"real": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"real": False}
    if not isinstance(data, dict):
        return {"real": False}
    data.setdefault("real", False)
    return data


def is_real(path: Path = DEFAULT_PATH) -> bool:
    return bool(load_settings(path).get("real"))


def set_real(value: bool, path: Path = DEFAULT_PATH) -> bool:
    with _lock:
        data = load_settings(path)
        data["real"] = bool(value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        return data["real"]


def _clamp_int(value: object, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def notify_config(path: Path = DEFAULT_PATH) -> dict:
    data = load_settings(path)
    days = _clamp_int(data.get("event_days"), 7, 1, 60)
    hours = _clamp_int(data.get("event_hours"), 6, 1, 168)
    if hours >= days * 24:
        hours = max(1, days * 24 - 1)
    return {
        "event_days": days,
        "event_hours": hours,
        "min_stars": _clamp_int(data.get("min_stars"), 1, 0, 5),
        "silent": bool(data.get("silent", True)),
        "watch": bool(data.get("watch", True)),
        "ignored": _ignored_ids(data.get("ignored")),
    }


def _ignored_ids(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text.isdigit() and text not in out:
            out.append(text)
    return out


def update_settings(values: dict, path: Path = DEFAULT_PATH) -> dict:
    with _lock:
        data = load_settings(path)
        data.update(values)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return data


def parse_real_arg(arg: str) -> bool | None:
    """None = toggle off (bare /real). True = /real 1. False = /real 0."""
    s = (arg or "").strip().lower()
    if s in {"1", "on", "true", "yes", "开", "开启"}:
        return True
    if s in {"0", "off", "false", "no", "关", "关闭"}:
        return False
    if s == "":
        return False
    return None
