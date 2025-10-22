from __future__ import annotations

import threading
import time
from collections import deque


class TokenBucket:
    """Simple thread-safe token bucket.

    - capacity: maximum tokens.
    - refill_rate_per_sec: tokens added per second.
    - acquire(n): block until n tokens available, then consume.
    """

    def __init__(self, capacity: int, refill_rate_per_sec: float) -> None:
        self.capacity = max(1, capacity)
        self.refill_rate_per_sec = float(refill_rate_per_sec)
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._cv = threading.Condition()

    def acquire(self, n: int = 1) -> None:
        if n <= 0:
            return
        with self._cv:
            while True:
                self._refill_locked()
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Wait for next refill opportunity
                now = time.monotonic()
                need = n - self._tokens
                # seconds needed at current refill rate
                wait_s = max(0.005, need / self.refill_rate_per_sec if self.refill_rate_per_sec > 0 else 0.25)
                self._cv.wait(timeout=wait_s)

    def _refill_locked(self) -> None:
        now = time.monotonic()
        delta = max(0.0, now - self._last)
        if delta <= 0:
            return
        self._last = now
        self._tokens = min(self.capacity, self._tokens + delta * self.refill_rate_per_sec)
        self._cv.notify_all()
