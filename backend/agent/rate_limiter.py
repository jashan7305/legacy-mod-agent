import asyncio
import time

class RateLimiter:
    def __init__(self, min_gap_seconds: float = 6.5):
        self.min_gap = min_gap_seconds
        self._last_call = 0.0

    async def wait(self):
        now = time.monotonic()
        time_elapsed = now - self._last_call
        if time_elapsed < self.min_gap:
            await asyncio.sleep(self.min_gap - time_elapsed)
        self._last_call = time.monotonic()