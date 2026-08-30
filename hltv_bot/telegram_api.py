from __future__ import annotations

import json
import logging
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hltv_bot.debuglog import clip
from hltv_bot.format import plain_to_rich

log = logging.getLogger("hltv_bot.tg")

TG_RETRY_AFTER_CAP = 15.0


def is_not_modified(exc: BaseException) -> bool:
    return "not modified" in str(exc).lower()


def retry_after_seconds(raw: str, default: float = 3.0, cap: float = TG_RETRY_AFTER_CAP) -> float:
    wait = default
    try:
        wait = float(json.loads(raw).get("parameters", {}).get("retry_after") or default)
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        pass
    return min(max(wait, 1.0), cap)


class Telegram:
    def __init__(self, token: str, timeout: float = 35.0):
        self.token = token
        self.timeout = timeout
        self.base = f"https://api.telegram.org/bot{token}"

    def _call(self, method: str, payload: dict) -> dict:
        rich = payload.get("rich_message") or {}
        html = rich.get("html") if isinstance(rich, dict) else None
        text = payload.get("text")
        log.debug(
            "tg %s chat=%s msg=%s html_len=%s text_len=%s skip=%s html=%s",
            method,
            payload.get("chat_id"),
            payload.get("message_id"),
            len(html) if isinstance(html, str) else None,
            len(text) if isinstance(text, str) else None,
            (rich.get("skip_entity_detection") if isinstance(rich, dict) else None),
            clip(html or text or "", 500),
        )
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
                    raw_body = resp.read().decode("utf-8")
                    body = json.loads(raw_body)
            except HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                log.warning("tg %s HTTP %s attempt=%s body=%s", method, e.code, attempt, clip(raw, 400))
                if e.code == 429:
                    time.sleep(retry_after_seconds(raw))
                    last_err = e
                    continue
                raise RuntimeError(f"telegram {method} HTTP {e.code}: {raw[:200]}") from e
            if not body.get("ok"):
                log.warning("tg %s not ok body=%s", method, clip(body, 400))
                raise RuntimeError(f"telegram {method} failed: {body}")
            result = body["result"]
            if isinstance(result, dict):
                log.debug(
                    "tg %s ok message_id=%s has_rich=%s",
                    method,
                    result.get("message_id"),
                    bool(result.get("rich_message")),
                )
            else:
                log.debug("tg %s ok type=%s", method, type(result).__name__)
            return result
        raise RuntimeError(f"telegram {method} rate limited: {last_err}")

    def get_updates(self, offset: int = 0, timeout: int = 25) -> list[dict]:
        q = urlencode(
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": json.dumps(["message", "my_chat_member"]),
            }
        )
        last_err: Exception | None = None
        for attempt in range(2):
            req = Request(f"{self.base}/getUpdates?{q}")
            try:
                with urlopen(req, timeout=timeout + 10) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                log.warning("getUpdates HTTP %s attempt=%s body=%s", e.code, attempt, clip(raw, 400))
                if e.code == 429:
                    time.sleep(retry_after_seconds(raw))
                    last_err = e
                    continue
                raise RuntimeError(f"telegram getUpdates HTTP {e.code}: {raw[:200]}") from e
            if not body.get("ok"):
                log.warning("getUpdates failed body=%s", clip(body, 400))
                raise RuntimeError(f"telegram getUpdates failed: {body}")
            rows = body.get("result") or []
            log.debug("getUpdates n=%s offset=%s", len(rows), offset)
            return rows
        raise RuntimeError(f"telegram getUpdates rate limited: {last_err}")

    def send_rich(
        self,
        chat_id: int | str,
        html: str,
        *,
        skip_entity_detection: bool = False,
    ) -> dict:
        return self._call(
            "sendRichMessage",
            {
                "chat_id": chat_id,
                "rich_message": {
                    "html": html,
                    "skip_entity_detection": skip_entity_detection,
                },
            },
        )

    def edit_rich(
        self,
        chat_id: int | str,
        message_id: int,
        html: str,
        *,
        skip_entity_detection: bool = False,
    ) -> dict:
        return self._call(
            "editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "rich_message": {
                    "html": html,
                    "skip_entity_detection": skip_entity_detection,
                },
            },
        )

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

    def chat_member_status(self, chat_id: int, user_id: int) -> str:
        try:
            r = self._call(
                "getChatMember",
                {"chat_id": chat_id, "user_id": user_id},
            )
            if isinstance(r, dict):
                return str(r.get("status") or "")
        except Exception:
            return ""
        return ""

    def chat_admin_user_ids(self, chat_id: int) -> set[int]:
        ids: set[int] = set()
        try:
            r = self._call("getChatAdministrators", {"chat_id": chat_id})
        except Exception:
            return ids
        if not isinstance(r, list):
            return ids
        for m in r:
            uid = (m.get("user") or {}).get("id")
            if uid is not None:
                ids.add(int(uid))
        return ids

    def set_my_commands(self, commands: list[dict], scope: dict | None = None) -> None:
        payload: dict = {"commands": commands}
        if scope:
            payload["scope"] = scope
        self._call("setMyCommands", payload)

    def delete_message(self, chat_id: int | str, message_id: int) -> None:
        try:
            self._call(
                "deleteMessage",
                {"chat_id": chat_id, "message_id": message_id},
            )
        except Exception:
            pass
