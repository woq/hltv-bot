from __future__ import annotations

import time
from threading import Lock


class Cooldown:
    """Allow a key at most once per interval seconds."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = Lock()

    def allow(self, key: str, interval: float) -> bool:
        if interval <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            prev = self._last.get(key, 0.0)
            if now - prev < interval:
                return False
            self._last[key] = now
            return True

    def remaining(self, key: str, interval: float) -> float:
        now = time.monotonic()
        with self._lock:
            prev = self._last.get(key, 0.0)
        left = interval - (now - prev)
        return left if left > 0 else 0.0
