"""Adaptive throttling.

Like Scrapling's AutoThrottle, each domain gets its own delay that starts low,
grows when the site blocks or slows down (honouring ``Retry-After``), and eases
back once responses look healthy again.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional
from urllib.parse import urlparse

from ..log import get_logger

logger = get_logger("throttle")


class AutoThrottle:
    def __init__(
        self,
        start_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_factor: float = 2.0,
        recovery_factor: float = 0.8,
    ):
        self.start_delay = start_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.recovery_factor = recovery_factor
        self._delays: dict[str, float] = {}
        self._last_request: dict[str, float] = {}

    def _domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def delay_for(self, url: str) -> float:
        return self._delays.get(self._domain(url), self.start_delay)

    def report_success(self, url: str) -> None:
        domain = self._domain(url)
        current = self._delays.get(domain, self.start_delay)
        self._delays[domain] = max(self.start_delay, current * self.recovery_factor)

    def report_block(self, url: str, retry_after: Optional[float] = None) -> None:
        domain = self._domain(url)
        current = self._delays.get(domain, self.start_delay)
        if retry_after and retry_after > 0:
            target = retry_after
        else:
            target = current * self.backoff_factor
        self._delays[domain] = min(self.max_delay, max(current, target))
        logger.debug("throttle: %s backed off to %.2fs", domain, self._delays[domain])

    async def wait(self, url: str) -> None:
        """Sleep until ``download_delay + adaptive delay`` elapsed since last hit."""
        domain = self._domain(url)
        now = time.monotonic()
        last = self._last_request.get(domain)
        delay = self.delay_for(url)
        if last is not None:
            elapsed = now - last
            remaining = delay - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_request[domain] = time.monotonic()

    def snapshot(self) -> dict[str, float]:
        return dict(self._delays)
