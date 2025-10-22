from __future__ import annotations

import threading
from queue import Queue, Empty
from typing import Iterable, Optional


class AddressQueue:
    """Thread-safe address queue with graceful stop and refill.

    Use add_many() to enqueue addresses, get_next() to retrieve with timeout,
    and stop() to signal end of work.
    """

    def __init__(self, maxsize: int = 10000) -> None:
        self._q: Queue[str] = Queue(maxsize=maxsize)
        self._stopped = threading.Event()

    def stop(self) -> None:
        self._stopped.set()

    def add_many(self, addresses: Iterable[str]) -> None:
        for addr in addresses:
            if self._stopped.is_set():
                break
            self._q.put(str(addr))

    def get_next(self, timeout: float = 0.25) -> Optional[str]:
        if self._stopped.is_set():
            return None
        try:
            return self._q.get(timeout=timeout)
        except Empty:
            return None
