from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from .address_queue import AddressQueue
from .rate_limiter import TokenBucket
from .checkers import get_checker_for_chain, BalanceResult


@dataclass
class ChainWorker:
    chain_key: str
    rate_limit_per_sec: float
    addresses: AddressQueue
    on_result: callable  # (BalanceResult) -> None

    def start(self) -> threading.Thread:
        limiter = TokenBucket(capacity=max(1, int(self.rate_limit_per_sec)), refill_rate_per_sec=self.rate_limit_per_sec)
        check = get_checker_for_chain(self.chain_key)

        def _loop() -> None:
            while True:
                addr = self.addresses.get_next(timeout=0.25)
                if addr is None:
                    # Could be temporarily empty, loop again; in real app we may exit on stop
                    time.sleep(0.05)
                    continue
                limiter.acquire(1)
                try:
                    res: BalanceResult = check(addr)
                    self.on_result(res)
                except Exception as exc:  # network/rpc errors are expected under public endpoints
                    self.on_result(BalanceResult(chain=self.chain_key, address=addr, raw_balance="error", display=f"error: {exc}"))

        t = threading.Thread(target=_loop, name=f"worker-{self.chain_key}", daemon=True)
        t.start()
        return t
