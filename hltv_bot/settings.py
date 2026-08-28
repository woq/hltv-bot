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
