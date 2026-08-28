from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

DEFAULT_CHATS_PATH = Path("data/chats.json")
_lock = Lock()


def _empty() -> dict:
    return {"groups": []}


def load_chats(path: Path = DEFAULT_CHATS_PATH) -> dict:
    if not path.exists():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return _empty()
    if not isinstance(data, dict) or not isinstance(data.get("groups"), list):
        return _empty()
    return data


def save_chats(data: dict, path: Path = DEFAULT_CHATS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def group_ids(path: Path = DEFAULT_CHATS_PATH) -> set[int]:
    ids: set[int] = set()
    for g in load_chats(path).get("groups") or []:
        try:
            ids.add(int(g["id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return ids


def add_group(chat_id: int, title: str = "", path: Path = DEFAULT_CHATS_PATH) -> bool:
    """Return True if newly added."""
    with _lock:
        data = load_chats(path)
        for g in data["groups"]:
            if int(g.get("id") or 0) == int(chat_id):
                g["title"] = title or g.get("title") or ""
                save_chats(data, path)
                return False
        data["groups"].append(
            {
                "id": int(chat_id),
                "title": title or "",
                "added_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        save_chats(data, path)
        return True


def remove_group(chat_id: int, path: Path = DEFAULT_CHATS_PATH) -> bool:
    with _lock:
        data = load_chats(path)
        before = len(data["groups"])
        data["groups"] = [g for g in data["groups"] if int(g.get("id") or 0) != int(chat_id)]
        save_chats(data, path)
        return len(data["groups"]) < before


def list_groups(path: Path = DEFAULT_CHATS_PATH) -> list[dict]:
    return list(load_chats(path).get("groups") or [])
