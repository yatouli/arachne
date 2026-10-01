"""Scheduling: request queue, robots.txt, adaptive throttle, deduplication."""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urlparse

from ..antidetect.throttle import AutoThrottle
from ..log import get_logger
from .request import Request

logger = get_logger("scheduler")


class RobotsCache:
    """Per-domain robots.txt check with caching."""

    def __init__(self, user_agent: str = "ArachneBot"):
        self.user_agent = user_agent
        self._cache: dict[str, Optional[object]] = {}

    def allowed(self, url: str) -> bool:
        import urllib.robotparser

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._cache.get(origin)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser()
            rp.set_url(f"{origin}/robots.txt")
            try:
                rp.read()
            except Exception:  # noqa: BLE001 - unreachable robots.txt => allow
                rp = None
            self._cache[origin] = rp
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.user_agent, url)
        except Exception:  # noqa: BLE001
            return True


class Scheduler:
    """An asyncio queue with deduplication, robots filtering and throttling."""

    def __init__(
        self,
        *,
        concurrency: int = 8,
        auto_throttle: bool = True,
        throttle_start: float = 1.0,
        throttle_max: float = 60.0,
        robots_obey: bool = False,
        max_requests: Optional[int] = None,
        user_agent: str = "ArachneBot",
    ):
        self.queue: asyncio.Queue[Request] = asyncio.Queue()
        self.seen: set[tuple[str, str]] = set()
        self.throttle = AutoThrottle(throttle_start, throttle_max)
        self.robots = RobotsCache(user_agent)
        self.concurrency = concurrency
        self.auto_throttle = auto_throttle
        self.robots_obey = robots_obey
        self.max_requests = max_requests
        self.scheduled = 0
        self.processed = 0

    def add(self, request: Request) -> bool:
        if self.max_requests is not None and self.scheduled >= self.max_requests:
            return False
        if not request.dont_filter:
            key = (request.method, request.url)
            if key in self.seen:
                return False
            self.seen.add(key)
        self.queue.put_nowait(request)
        self.scheduled += 1
        return True

    async def get(self) -> Request:
        return await self.queue.get()

    def task_done(self) -> None:
        self.queue.task_done()

    async def wait(self, url: str) -> None:
        if self.auto_throttle:
            await self.throttle.wait(url)

    def report_success(self, url: str) -> None:
        if self.auto_throttle:
            self.throttle.report_success(url)

    def report_block(self, url: str, retry_after: Optional[float] = None) -> None:
        if self.auto_throttle:
            self.throttle.report_block(url, retry_after)

    def allowed_by_robots(self, url: str) -> bool:
        return (not self.robots_obey) or self.robots.allowed(url)
