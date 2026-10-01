"""Sitemap 自动发现与全站爬取。

只需给一个域名，自动从 robots.txt 和常见路径发现 sitemap.xml，
递归解析 urlset/sitemapindex，再对页面 URL 做提取。
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional
from urllib.parse import urlparse

from ..log import get_logger
from .request import Request
from .spider import Spider, _extract_one

logger = get_logger("sitemap")

_COMMON_PATHS = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap.php",
    "/wp-sitemap.xml",
]


def _origin(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


def discover_sitemap_urls(url: str, fetcher=None) -> list[str]:
    """Find sitemap URLs for a site via robots.txt + common paths."""
    from ..fetchers.http import Fetcher

    fetcher = fetcher or Fetcher()
    origin = _origin(url)
    found: list[str] = []
    seen: set[str] = set()

    # 1. robots.txt 里的 Sitemap: 指令
    try:
        page = fetcher._fetch(origin + "/robots.txt", raise_on_block=False)
        for line in page.text.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap = line.split(":", 1)[1].strip()
                if sitemap and sitemap not in seen:
                    seen.add(sitemap)
                    found.append(sitemap)
    except Exception:  # noqa: BLE001
        pass

    # 2. 常见路径探测
    for path in _COMMON_PATHS:
        candidate = origin + path
        if candidate in seen:
            continue
        try:
            page = fetcher._fetch(candidate, raise_on_block=False)
            if page.status_code == 200 and ("<urlset" in page.text or "<sitemapindex" in page.text):
                seen.add(candidate)
                found.append(candidate)
        except Exception:  # noqa: BLE001
            continue
    return found


def resolve_sitemap_urls(sitemap_urls: list[str], fetcher=None, max_urls: int = 10000) -> list[str]:
    """Fetch sitemap(s) and return every page URL (following nested sitemapindex)."""
    from lxml import etree

    fetcher = fetcher
    urls: list[str] = []
    queue = list(sitemap_urls)
    seen_sitemaps: set[str] = set()
    while queue and len(urls) < max_urls:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            page = fetcher._fetch(sitemap_url, raise_on_block=False)
            if page.status_code != 200:
                continue
            root = etree.fromstring(page.text.encode("utf-8"))
            # 嵌套的 sitemapindex
            for loc in root.xpath("//*[local-name()='sitemap']/*[local-name()='loc']/text()"):
                nested = loc.strip()
                if nested and nested not in seen_sitemaps:
                    queue.append(nested)
            # 页面 URL
            for loc in root.xpath("//*[local-name()='url']/*[local-name()='loc']/text()"):
                u = loc.strip()
                if u and u not in urls:
                    urls.append(u)
                if len(urls) >= max_urls:
                    break
        except Exception as exc:  # noqa: BLE001
            logger.debug("sitemap parse failed %s: %s", sitemap_url, exc)
            continue
    return urls


class SitemapSpider(Spider):
    """Crawl the URLs listed in a site's sitemap(s).

    * ``sitemap_urls``: pre-discovered sitemap URLs (fetched & parsed on start),
      or ``urls``: page URLs to crawl directly.
    * ``fields``: ``{name: css_selector}``, or empty for auto readable extraction.
    """

    def __init__(
        self,
        sitemap_urls: Optional[list[str]] = None,
        urls: Optional[list[str]] = None,
        fields: Optional[dict[str, str]] = None,
        image_field: Optional[str] = None,
        download_dir: str = "downloads",
        limit: Optional[int] = None,
        **kw: Any,
    ):
        self._sitemap_urls = list(sitemap_urls or [])
        self._urls = list(urls or [])
        self._fields = dict(fields or {})
        self._image_field = image_field
        self._download_dir = download_dir
        self._limit = limit
        self.downloaded = 0
        super().__init__(**kw)

    def start_requests(self):
        fetcher = self._fetcher_for("http")
        if self._sitemap_urls and not self._urls:
            self._urls = resolve_sitemap_urls(self._sitemap_urls, fetcher)
        urls = self._urls[: self._limit] if self._limit else self._urls
        for url in urls:
            yield Request(url, callback=self.parse_item)

    async def parse_item(self, response: Response):
        if not self._fields:
            yield response.page.readable()
            return
        record: dict[str, Any] = {
            name: _extract_one(response, selector) for name, selector in self._fields.items()
        }
        if self._image_field and record.get(self._image_field):
            from urllib.parse import urljoin

            absolute = urljoin(response.url, record[self._image_field])
            try:
                img = await self._fetcher_for("http").afetch(absolute)
                os.makedirs(self._download_dir, exist_ok=True)
                filename = re.sub(r"\W+", "_", absolute.rsplit("/", 1)[-1] or "image.jpg")
                with open(os.path.join(self._download_dir, filename), "wb") as fh:
                    fh.write(img.content)
                self.downloaded += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("image download failed %s: %s", absolute, exc)
        yield record
