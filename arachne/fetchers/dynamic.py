"""Full-browser fetcher (Playwright) for JavaScript-heavy sites."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Optional, Pattern

from ..exceptions import FetcherError
from ..log import get_logger
from ..page import CapturedResponse, Page
from .base import FetcherBase

logger = get_logger("dynamic")

try:
    from playwright.sync_api import Browser, BrowserContext, sync_playwright

    _HAS_PLAYWRIGHT = True
except Exception:  # noqa: BLE001
    sync_playwright = None
    _HAS_PLAYWRIGHT = False

if not _HAS_PLAYWRIGHT:
    logger.warning(
        "playwright is not installed; DynamicFetcher/StealthyFetcher are unavailable. "
        "Install with `pip install arachne[stealth]` then `playwright install chromium`."
    )


class DynamicFetcher(FetcherBase):
    """Render pages in a real browser and return the final DOM.

    Parameters to :meth:`fetch`:
      * ``wait_until``: ``"load" | "domcontentloaded" | "networkidle" | "commit"``
      * ``capture_xhr``: a regex/str pattern — matching XHR/fetch responses are
        collected on ``page.captured_xhr``.
      * ``scroll``: number of incremental scrolls (for infinite-feed sites).
      * ``wait``: extra milliseconds to wait after load.
      * ``screenshot``: optional path to save a PNG.
      * ``js``: JavaScript to evaluate before returning (can return JSON).
    """

    name = "dynamic"
    supports_async = True

    def __init__(self, settings=None, **overrides):
        super().__init__(settings, **overrides)
        self._pw = None
        self._browser: Optional["Browser"] = None
        self._launch_lock = threading.Lock()

    # ---- browser lifecycle ---------------------------------------------
    def _get_browser(self) -> "Browser":
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        if not _HAS_PLAYWRIGHT:
            raise FetcherError("playwright is required for DynamicFetcher")
        with self._launch_lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            self._pw = sync_playwright().start()
            browser_type = getattr(self._pw, self.settings.browser_type, None)
            if browser_type is None:
                self._pw.stop()
                raise FetcherError(f"unknown browser_type {self.settings.browser_type!r}")
            try:
                self._browser = browser_type.launch(headless=self.settings.headless)
            except Exception as exc:  # noqa: BLE001
                raise FetcherError(
                    f"could not launch {self.settings.browser_type}; run "
                    f"`playwright install {self.settings.browser_type}`: {exc}"
                ) from exc
        return self._browser

    def _new_context(self, extra_headers: Optional[dict] = None) -> "BrowserContext":
        browser = self._get_browser()
        proxy = self._proxy()
        context_options: dict[str, Any] = {
            "viewport": self.settings.viewport or {"width": 1920, "height": 1080},
            "locale": self.settings.locale,
            "timezone_id": self.settings.timezone,
            "user_agent": self.settings.user_agent or self._headers().get("user-agent"),
        }
        if proxy:
            context_options["proxy"] = {"server": proxy}
            if self.settings.proxy_auth:
                context_options["proxy"]["username"] = self.settings.proxy_auth[0]
                context_options["proxy"]["password"] = self.settings.proxy_auth[1]
        if extra_headers:
            context_options["extra_http_headers"] = extra_headers
        return browser.new_context(**context_options)

    def _do_fetch(self, url: str, method: str, session_id: str, **kwargs) -> Page:
        wait_until = kwargs.pop("wait_until", "networkidle")
        capture_xhr = kwargs.pop("capture_xhr", None)
        scroll = kwargs.pop("scroll", 0)
        wait_ms = kwargs.pop("wait", 0)
        screenshot = kwargs.pop("screenshot", None)
        js = kwargs.pop("js", None)
        extra_headers = kwargs.pop("headers", None)

        context = self._new_context(extra_headers)
        captured: list[CapturedResponse] = []
        try:
            page = context.new_page()
            if capture_xhr is not None:
                pattern = _to_regex(capture_xhr)

                def _on_response(response):
                    if response.resource_type in ("xhr", "fetch") and pattern.search(response.url):
                        try:
                            body = response.text()
                        except Exception:  # noqa: BLE001
                            body = ""
                        captured.append(CapturedResponse(
                            url=response.url,
                            method=response.request.method,
                            status=response.status,
                            headers=dict(response.headers),
                            body=body,
                        ))

                page.on("response", _on_response)

            start = time.perf_counter()
            response = page.goto(url, wait_until=wait_until, timeout=self.settings.timeout * 1000)
            status = response.status if response is not None else 200
            if scroll:
                for _ in range(scroll):
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(400)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            content = page.content()
            duration = time.perf_counter() - start
            meta: dict[str, Any] = {}
            if js:
                meta["js_result"] = page.evaluate(js)
            if screenshot:
                page.screenshot(path=screenshot, full_page=True)
            return self._to_page(
                url, status, content.encode("utf-8"),
                _headers_from_response(response), duration, session_id,
                captured_xhr=captured, request_headers=extra_headers, **meta,
            )
        finally:
            context.close()

    async def afetch(self, url: str, method: str = "GET", *, session_id: str = "default",
                     raise_on_block: bool = True, **kwargs) -> Page:
        import asyncio

        return await asyncio.to_thread(self._fetch, url, method, session_id=session_id,
                                       raise_on_block=raise_on_block, **kwargs)

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
            self._pw = None


def _to_regex(pattern) -> Pattern:
    import re

    return re.compile(pattern) if isinstance(pattern, str) else pattern


def _headers_from_response(response) -> dict[str, str]:
    if response is None:
        return {}
    try:
        return {k.lower(): v for k, v in response.headers.items()}
    except Exception:  # noqa: BLE001
        return {}
