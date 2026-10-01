"""Arachne — an adaptive AI web-scraping framework.

Arachne draws inspiration from `Scrapling <https://github.com/D4Vinci/Scrapling>`_
and bundles everything a modern scraper needs under one roof:

* a **plugin system** for per-site scraping logic (write once, reuse everywhere),
* **anti-anti-bot** engines (TLS/HTTP2 fingerprint impersonation, browser
  fingerprint spoofing, proxy rotation, adaptive throttling, challenge detection),
* **JS reverse-engineering** helpers (embedded JS execution, XHR capture,
  signature discovery & invocation),
* an **adaptive parser** that relocates your selectors when a site changes,
* an optional **AI layer** that writes selectors/schemas from page structure,
* a **Scrapy-like spider** framework with concurrent crawling.

Quick start::

    from arachne import Fetcher

    page = Fetcher.fetch("https://example.com", impersonate="chrome124")
    print(page.css("title::text").get())
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]

# Import lazily to keep the import path cheap and optional-dependency friendly.
from . import config, exceptions, log  # noqa: E402


def __getattr__(name: str):
    """Lazy top-level exports so importing ``arachne`` never forces heavy deps."""
    if name == "Fetcher":
        from .fetchers.http import Fetcher

        return Fetcher
    if name == "StealthyFetcher":
        from .fetchers.stealth import StealthyFetcher

        return StealthyFetcher
    if name == "DynamicFetcher":
        from .fetchers.dynamic import DynamicFetcher

        return DynamicFetcher
    if name == "Spider":
        from .spider.spider import Spider

        return Spider
    if name == "CrawlSpider":
        from .spider.spider import CrawlSpider

        return CrawlSpider
    if name == "SitePlugin":
        from .plugins.base import SitePlugin

        return SitePlugin
    if name == "JsEngine":
        from .js_reverse.engine import JsEngine

        return JsEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
