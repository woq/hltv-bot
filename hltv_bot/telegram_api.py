from __future__ import annotations

import json
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class Telegram:
    def __init__(self, token: str, timeout: float = 35.0):
        self.token = token
        self.timeout = timeout
        self.base = f"https://api.telegram.org/bot{token}"

    def _call(self, method: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        last_err: Exception | None = None
        for attempt in range(2):
            req = Request(
                f"{self.base}/{method}",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                if e.code == 429:
                    wait = 3
                    try:
                        wait = int(json.loads(raw).get("parameters", {}).get("retry_after") or 3)
                    except json.JSONDecodeError:
                        pass
                    time.sleep(min(max(wait, 1), 15))
                    last_err = e
                    continue
                raise RuntimeError(f"telegram {method} HTTP {e.code}: {raw[:200]}") from e
            if not body.get("ok"):
                raise RuntimeError(f"telegram {method} failed: {body}")
            return body["result"]
        raise RuntimeError(f"telegram {method} rate limited: {last_err}")

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict]:
        q = urlencode(
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": json.dumps(["message", "my_chat_member"]),
            }
        )
        req = Request(f"{self.base}/getUpdates?{q}")
        with urlopen(req, timeout=timeout + 10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError(f"telegram getUpdates failed: {body}")
        return body.get("result") or []

    def send_message(self, chat_id: int | str, text: str) -> dict:
        return self._call(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )

    def edit_message(self, chat_id: int | str, message_id: int, text: str) -> dict:
        return self._call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )

    def delete_message(self, chat_id: int | str, message_id: int) -> None:
        try:
            self._call(
                "deleteMessage",
                {"chat_id": chat_id, "message_id": message_id},
            )
        except Exception:
            pass
