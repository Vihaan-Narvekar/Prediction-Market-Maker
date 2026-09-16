import asyncio
import time
import math


class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        if not all(math.isfinite(x) and x > 0 for x in (capacity, refill_rate)):
            raise ValueError("Rate and capacity must be finite and positive")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, cost: float = 1.0) -> None:
        if not math.isfinite(cost) or not 0 < cost <= self.capacity:
            raise ValueError("Cost must be positive and no larger than capacity")
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= cost:
                    self.tokens -= cost
                    return
                await asyncio.sleep((cost - self.tokens) / self.refill_rate)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
