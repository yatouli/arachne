"""Spider framework: Spider, CrawlSpider, and the async crawl engine."""

from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Optional

from ..config import Settings
from ..exceptions import BlockedError, FetcherError
from ..log import get_logger
from .link import LinkExtractor
from .request import Request
from .response import Response
from .scheduler import Scheduler

logger = get_logger("spider")


@dataclass
class Stats:
    start_time: float = 0.0
    finish_time: float = 0.0
    scheduled: int = 0
    processed: int = 0
    items: int = 0
    blocked: int = 0
    errors: int = 0

    @property
    def duration(self) -> float:
        return self.finish_time - self.start_time

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_time": self.start_time,
            "finish_time": self.finish_time,
            "duration": self.duration,
            "scheduled": self.scheduled,
            "processed": self.processed,
            "items": self.items,
            "blocked": self.blocked,
            "errors": self.errors,
        }


@dataclass
class CrawlResult:
    items: list[dict[str, Any]]
    stats: Stats

    def to_json(self) -> str:
        import json

        return json.dumps(self.items, ensure_ascii=False, indent=2)

    def to_jsonl(self) -> str:
        import json

        return "\n".join(json.dumps(i, ensure_ascii=False) for i in self.items)

    def to_csv(self) -> str:
        import csv
        import io

        if not self.items:
            return ""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(self.items[0].keys()))
        writer.writeheader()
        for item in self.items:
            writer.writerow(item)
        return buf.getvalue()


@dataclass
class Rule:
    """A CrawlSpider rule: extract links and (optionally) follow them."""

    link_extractor: LinkExtractor
    callback: Optional[Callable] = None
    follow: bool = False
    process_links: Optional[Callable[[list[str]], list[str]]] = None


class Spider:
    """Scrapy-like async spider.

    Subclass and override :meth:`parse`::

        class MySpider(Spider):
            name = "demo"
            start_urls = ["https://example.com"]

            async def parse(self, response):
                for item in response.css(".product"):
                    yield {"title": item.css("h2::text").get()}
    """

    name: str = ""
    start_urls: list[str] = []
    custom_settings: dict[str, Any] = {}
    fetcher_name: str = "http"

    def __init__(self, settings: Optional[Settings] = None, **overrides: Any):
        merged = dict(self.custom_settings)
        merged.update(overrides)
        self.settings = (settings or Settings()).merge(**merged)
        self.scheduler = Scheduler(
            concurrency=self.settings.concurrency,
            auto_throttle=self.settings.auto_throttle,
            throttle_start=self.settings.auto_throttle_start,
            throttle_max=self.settings.auto_throttle_max,
            robots_obey=self.settings.robots_obey,
            max_requests=self.settings.max_requests,
            user_agent=self.settings.user_agent or "ArachneBot",
        )
        self.items: list[dict[str, Any]] = []
        self.stats = Stats()
        self._fetchers: dict[str, Any] = {}
        self._stream_queue: Optional[asyncio.Queue] = None

    # ---- fetchers -------------------------------------------------------
    def _fetcher_for(self, kind: Optional[str]):
        kind = kind or self.fetcher_name
        if kind not in self._fetchers:
            if kind == "dynamic":
                from ..fetchers.dynamic import DynamicFetcher

                self._fetchers[kind] = DynamicFetcher(self.settings)
            elif kind == "stealth":
                from ..fetchers.stealth import StealthyFetcher

                self._fetchers[kind] = StealthyFetcher(self.settings)
            else:
                from ..fetchers.http import Fetcher

                self._fetchers[kind] = Fetcher(self.settings)
        return self._fetchers[kind]

    # ---- lifecycle ------------------------------------------------------
    def start_requests(self):
        for url in self.start_urls:
            yield Request(url, callback=self.parse)

    async def parse(self, response: Response):
        """Default no-op; override this."""
        return None

    # ---- engine ---------------------------------------------------------
    def run(self) -> CrawlResult:
        """Run the crawl to completion (synchronous wrapper)."""
        return asyncio.run(self._crawl())

    async def crawl(self) -> CrawlResult:
        return await self._crawl()

    def stream(self) -> AsyncIterator[dict[str, Any]]:
        """Async-iterate items as they are scraped."""
        return self._stream()

    async def _crawl(self) -> CrawlResult:
        self.items = []
        self.stats = Stats(start_time=time.time())
        async for request in self._consume(self.start_requests()):
            self.scheduler.add(request)
        await self._run_workers()
        self.stats.scheduled = self.scheduler.scheduled
        self.stats.finish_time = time.time()
        self._close()
        return CrawlResult(items=self.items, stats=self.stats)

    async def _stream(self) -> AsyncIterator[dict[str, Any]]:
        self.items = []
        self.stats = Stats(start_time=time.time())
        self._stream_queue = asyncio.Queue()
        async for request in self._consume(self.start_requests()):
            self.scheduler.add(request)

        workers = [
            asyncio.create_task(self._worker()) for _ in range(self.scheduler.concurrency)
        ]

        async def drain():
            await self.scheduler.queue.join()
            for _ in range(self.scheduler.concurrency):
                self.scheduler.queue.put_nowait(None)
            await asyncio.gather(*workers, return_exceptions=True)
            self.stats.finish_time = time.time()

        drain_task = asyncio.create_task(drain())
        while not (drain_task.done() and self._stream_queue.empty()):
            try:
                item = await asyncio.wait_for(self._stream_queue.get(), timeout=0.1)
                yield item
            except asyncio.TimeoutError:
                continue
        await drain_task
        self.stats.scheduled = self.scheduler.scheduled
        self._close()

    async def _run_workers(self) -> None:
        workers = [
            asyncio.create_task(self._worker()) for _ in range(self.scheduler.concurrency)
        ]
        await self.scheduler.queue.join()
        for _ in range(self.scheduler.concurrency):
            self.scheduler.queue.put_nowait(None)
        await asyncio.gather(*workers, return_exceptions=True)

    async def _worker(self) -> None:
        while True:
            request = await self.scheduler.get()
            if request is None:
                return
            try:
                await self._process(request)
            except Exception as exc:  # noqa: BLE001
                self.stats.errors += 1
                logger.exception("error processing %s: %s", request.url, exc)
            finally:
                self.scheduler.task_done()

    async def _process(self, request: Request) -> None:
        if not self.scheduler.allowed_by_robots(request.url):
            logger.debug("skipping (robots.txt): %s", request.url)
            return
        await self.scheduler.wait(request.url)
        fetcher = self._fetcher_for(request.fetcher)
        try:
            page = await fetcher.afetch(
                request.url,
                request.method,
                session_id=request.session_id,
                headers=request.headers,
                params=request.params,
                data=request.data,
                json=request.json,
                cookies=request.cookies,
            )
        except BlockedError as exc:
            self.stats.blocked += 1
            self.scheduler.report_block(request.url)
            logger.warning("blocked on %s: %s", request.url, exc)
            if request.errback is not None:
                await self._maybe_await(request.errback, exc)
            return
        except FetcherError as exc:
            self.stats.errors += 1
            logger.warning("fetch error on %s: %s", request.url, exc)
            if request.errback is not None:
                await self._maybe_await(request.errback, exc)
            return

        self.scheduler.report_success(request.url)
        self.stats.processed += 1
        response = Response(request, page)
        callback = request.callback or self.parse
        result = callback(response)
        async for item in self._iterate(result):
            if isinstance(item, Request):
                self.scheduler.add(item)
            else:
                self.items.append(_to_dict(item))
                self.stats.items += 1
                if self._stream_queue is not None:
                    self._stream_queue.put_nowait(_to_dict(item))

    @staticmethod
    async def _iterate(result: Any):
        if result is None:
            return
        if inspect.isasyncgen(result):
            async for x in result:
                yield x
            return
        if inspect.isawaitable(result):
            result = await result
        for x in _sync_iter(result):
            yield x

    @staticmethod
    async def _maybe_await(fn: Callable, *args):
        result = fn(*args)
        if inspect.isawaitable(result):
            await result

    @staticmethod
    async def _consume(gen):
        if inspect.isasyncgen(gen):
            async for x in gen:
                yield x
        else:
            for x in gen:
                yield x

    def _close(self) -> None:
        for fetcher in self._fetchers.values():
            try:
                fetcher.close()
            except Exception:  # noqa: BLE001
                pass
        self._fetchers.clear()


def _sync_iter(result: Any):
    if isinstance(result, (list, tuple)):
        yield from result
    elif isinstance(result, (dict, Request)):
        yield result
    elif isinstance(result, (str, bytes)):
        return
    elif hasattr(result, "__iter__"):
        yield from result


def _to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    to_dict = getattr(item, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    return dict(item)


class CrawlSpider(Spider):
    """A Spider that follows links according to :attr:`rules`."""

    rules: list[Rule] = []

    async def parse(self, response: Response):
        for rule in self.rules:
            links = rule.link_extractor.extract_links(response)
            if rule.process_links is not None:
                links = rule.process_links(links)
            for link in links:
                yield Request(link, callback=rule.callback or (self.parse if rule.follow else None))


class ConfigSpider(Spider):
    """A Spider configured by data instead of subclassing.

    Useful for driving crawls from a UI / JSON config:

    * ``start_url``: the list page.
    * ``link_regex``: regex matched against each ``<a href>``; matches become
      detail pages.
    * ``fields``: ``{name: css_selector}`` extracted from each detail page.
    * ``pages``: number of list pages (appends ``?page=N``).
    * ``image_field``: name of a field whose value is an image URL to download.
    * ``download_dir``: where images are saved.
    """

    def __init__(
        self,
        start_url: str,
        link_regex: Optional[str] = None,
        fields: Optional[dict[str, str]] = None,
        pages: int = 1,
        image_field: Optional[str] = None,
        download_dir: str = "downloads",
        auto_links: bool = False,
        **kw: Any,
    ):
        self._link_regex = re.compile(link_regex) if link_regex else None
        self._fields = dict(fields or {})
        self._image_field = image_field
        self._download_dir = download_dir
        self._auto_links = auto_links
        self.downloaded: int = 0
        self.start_urls = _paginate_urls(start_url, pages)
        super().__init__(**kw)

    async def parse(self, response: Response):
        if self._link_regex is None:
            if self._auto_links:
                # 自动识别列表项里的详情链接
                from ..parsing.autolist import extract_item_links

                for link in extract_item_links(response.page):
                    yield response.follow(link, callback=self.parse_item)
                return
            # No link pattern: treat start_url itself as a detail page.
            async for item in self._parse_item(response):
                yield item
            return
        for href in response.css("a::attr(href)").getall():
            if href and self._link_regex.search(href):
                yield response.follow(href, callback=self.parse_item)

    async def parse_item(self, response: Response):
        async for item in self._parse_item(response):
            yield item

    async def _parse_item(self, response: Response):
        if not self._fields:
            # 没有手动字段：自动正文提取（readable）
            yield response.page.readable()
            return
        record: dict[str, Any] = {}
        for name, selector in self._fields.items():
            record[name] = _extract_one(response, selector)
        if self._image_field and record.get(self._image_field):
            from urllib.parse import urljoin

            absolute = urljoin(response.url, record[self._image_field])
            try:
                img = await self._fetcher_for("http").afetch(absolute)
                os.makedirs(self._download_dir, exist_ok=True)
                filename = re.sub(r"\W+", "_", absolute.rsplit("/", 1)[-1] or "image.jpg")
                if "." not in filename.split("_")[-1]:
                    filename += ".jpg"
                with open(os.path.join(self._download_dir, filename), "wb") as fh:
                    fh.write(img.content)
                self.downloaded += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("image download failed %s: %s", absolute, exc)
        yield record


def _paginate_urls(start_url: str, pages: int) -> list[str]:
    urls = [start_url]
    for n in range(2, max(1, pages) + 1):
        sep = "&" if "?" in start_url else "?"
        urls.append(f"{start_url}{sep}page={n}")
    return urls


def _extract_one(response: Response, selector: str) -> Any:
    from ..parsing.selector import clean_text

    if selector.endswith("::text") or "::text" in selector:
        return "\n".join(response.css(selector).getall()) or None
    if "::attr" in selector:
        return response.css(selector).get()
    first = response.css(selector).first
    return first.text() if first is not None else None
