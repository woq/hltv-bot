from __future__ import annotations

import time
from threading import Lock


class Gap:
    """Sleep so consecutive calls are at least `interval` seconds apart."""

    def __init__(self) -> None:
        self._last = 0.0
        self._lock = Lock()

    def sleep(self, interval: float) -> float:
        if interval <= 0:
            with self._lock:
                self._last = time.monotonic()
            return 0.0
        with self._lock:
            now = time.monotonic()
            wait = interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            return wait if wait > 0 else 0.0


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
