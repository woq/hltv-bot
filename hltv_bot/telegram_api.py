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
EDIT_429_RETRY_CAP = 60.0


class TelegramRateLimit(RuntimeError):
    """HTTP 429. Watch edits must freeze rather than block the scorebot thread."""

    def __init__(self, retry_after: float, *, method: str = "") -> None:
        self.retry_after = float(retry_after)
        self.method = method
        super().__init__(f"telegram {method} rate limited retry_after={self.retry_after:.0f}s")


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

    def _call(self, method: str, payload: dict, *, retry_429: bool = True) -> dict:
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
                    wait = retry_after_seconds(raw, cap=EDIT_429_RETRY_CAP if not retry_429 else TG_RETRY_AFTER_CAP)
                    if not retry_429:
                        raise TelegramRateLimit(wait, method=method) from e
                    time.sleep(wait)
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
            retry_429=False,
        )

    def send_message(self, chat_id: int | str, text: str, *, silent: bool = False) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if silent:
            payload["disable_notification"] = True
        return self._call("sendMessage", payload)

    def send_photo(
        self,
        chat_id: int | str,
        photo_bytes: bytes,
        *,
        caption: str = "",
        filename: str = "matches.png",
    ) -> dict:
        import uuid

        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
        body_parts: list[bytes] = []
        fields = {"chat_id": str(chat_id)}
        if caption:
            fields["caption"] = caption[:1024]
            fields["parse_mode"] = "HTML"
        for k, v in fields.items():
            body_parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8")
            )
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"{filename}\"\r\n"
            f"Content-Type: image/png\r\n\r\n".encode("utf-8")
            + photo_bytes
            + b"\r\n"
        )
        body_parts.append(f"--{boundary}--\r\n".encode("utf-8"))
        data = b"".join(body_parts)

        log.debug("tg sendPhoto chat=%s photo_len=%s cap_len=%s", chat_id, len(photo_bytes), len(caption))
        last_err: Exception | None = None
        for attempt in range(2):
            req = Request(
                f"{self.base}/sendPhoto",
                data=data,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                method="POST",
            )
            try:
                with urlopen(req, timeout=self.timeout) as resp:
                    raw_body = resp.read().decode("utf-8")
                    body = json.loads(raw_body)
            except HTTPError as e:
                raw = e.read().decode("utf-8", "replace")
                log.warning("tg sendPhoto HTTP %s attempt=%s body=%s", e.code, attempt, clip(raw, 400))
                if e.code == 429:
                    time.sleep(retry_after_seconds(raw))
                    last_err = e
                    continue
                raise RuntimeError(f"telegram sendPhoto HTTP {e.code}: {raw[:200]}") from e
            if not body.get("ok"):
                log.warning("tg sendPhoto not ok body=%s", clip(body, 400))
                raise RuntimeError(f"telegram sendPhoto failed: {body}")
            result = body["result"]
            return result
        raise RuntimeError(f"telegram sendPhoto rate limited: {last_err}")

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

    def send_chat_action(self, chat_id: int | str, action: str = "upload_photo") -> dict:
        try:
            return self._call("sendChatAction", {"chat_id": chat_id, "action": action})
        except Exception:
            return {}

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

    def bot_can_delete_messages(self, chat_id: int | str, bot_user_id: int | None = None) -> bool:
        """Check if bot has administrator permission to delete messages in a group."""
        try:
            cid = int(chat_id)
            if cid > 0:
                # Direct private chat
                return True
            # In group/supergroup: check bot member status/permissions
            # If bot_user_id is not given, extract from token (before ':')
            buid = bot_user_id
            if buid is None and ":" in self.token:
                try:
                    buid = int(self.token.split(":", 1)[0])
                except (ValueError, TypeError):
                    buid = None
            if buid:
                r = self._call("getChatMember", {"chat_id": cid, "user_id": buid})
                if isinstance(r, dict):
                    status = str(r.get("status") or "")
                    if status == "creator":
                        return True
                    if status == "administrator":
                        return bool(r.get("can_delete_messages", False))
                    return False
        except Exception as e:
            log.debug("bot_can_delete_messages check failed chat=%s: %s", chat_id, e)
        return False

    def delete_message(self, chat_id: int | str, message_id: int) -> None:
        try:
            self._call(
                "deleteMessage",
                {"chat_id": chat_id, "message_id": message_id},
            )
        except Exception:
            pass
