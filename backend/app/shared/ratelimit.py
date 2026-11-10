"""Small in-memory sliding-window rate limiter (single process is enough for the demo)."""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_s: float):
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str) -> bool:
        """Record one attempt. Returns False when the key is over its limit."""
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def blocked(self, key: str) -> bool:
        """True when the key is at its limit (without recording an attempt)."""
        now = time.monotonic()
        return sum(1 for t in self._hits[key] if now - t <= self.window_s) >= self.limit

    def reset(self) -> None:
        self._hits.clear()


deposit_limiter = RateLimiter(limit=5, window_s=600)  # per client IP
login_limiter = RateLimiter(limit=10, window_s=60)  # per client IP
device_code_limiter = RateLimiter(limit=5, window_s=60)  # wrong codes per locker


def reset_all() -> None:
    for limiter in (deposit_limiter, login_limiter, device_code_limiter):
        limiter.reset()
