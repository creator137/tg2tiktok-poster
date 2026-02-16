from __future__ import annotations

import asyncio
import time
from collections import deque


class AsyncPerAccountRateLimiter:
    def __init__(self, limit_per_minute: int) -> None:
        self.limit_per_minute = max(1, limit_per_minute)
        self._events: dict[str, deque[float]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def wait(self, account_label: str) -> None:
        lock = self._locks.setdefault(account_label, asyncio.Lock())
        async with lock:
            events = self._events.setdefault(account_label, deque())
            now = time.monotonic()
            self._trim(events, now)
            if len(events) >= self.limit_per_minute:
                delay = 60 - (now - events[0])
                if delay > 0:
                    await asyncio.sleep(delay)
                now = time.monotonic()
                self._trim(events, now)
            events.append(time.monotonic())

    @staticmethod
    def _trim(events: deque[float], now: float) -> None:
        while events and (now - events[0] >= 60):
            events.popleft()

