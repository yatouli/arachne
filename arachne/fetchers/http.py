"""Stealth HTTP fetcher.

Uses ``curl_cffi`` (curl-impersonate bindings) to spoof the browser's TLS and
HTTP/2 fingerprint — the single most effective anti-bot trick for plain HTTP.
When ``curl_cffi`` is missing it degrades to ``httpx`` (no TLS impersonation)
and logs a one-time warning.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from ..exceptions import FetcherError
from ..log import get_logger
from .base import FetcherBase

logger = get_logger("http")

try:  # pragma: no cover - optional dependency
    from curl_cffi import requests as curl_requests

    _HAS_CURL_CFFI = True
except Exception:  # noqa: BLE001
    curl_requests = None
    _HAS_CURL_CFFI = False

from ..antidetect.fingerprints import DEFAULT_IMPERSONATE, is_supported

try:
    import httpx

    _HAS_HTTPX = True
except Exception:  # noqa: BLE001
    httpx = None
    _HAS_HTTPX = False

if not _HAS_CURL_CFFI:
    logger.warning(
        "curl_cffi is not installed; TLS fingerprint impersonation is DISABLED. "
        "Install it with `pip install arachne[stealth]` (or `pip install curl_cffi`)."
    )


class Fetcher(FetcherBase):
    """Fast, stealthy HTTP requests with browser fingerprint impersonation."""

    name = "http"
    supports_async = True

    def __init__(self, settings=None, **overrides):
        super().__init__(settings, **overrides)
        self._session: Any = None
        self._session_key: Optional[str] = None

    # ---- transport ------------------------------------------------------
    def _get_client(self) -> Any:
        impersonate = self.settings.impersonate or DEFAULT_IMPERSONATE
        # Guard against curl_cffi version drift: fall back to a supported
        # target instead of failing mid-request, and keep headers coherent.
        if _HAS_CURL_CFFI and not is_supported(impersonate):
            logger.warning(
                "impersonate %r is not supported by curl_cffi; falling back to %r",
                impersonate, DEFAULT_IMPERSONATE,
            )
            impersonate = DEFAULT_IMPERSONATE
            self.settings.impersonate = impersonate
        key = impersonate
        if self._session is not None and self._session_key == key:
            return self._session
        if _HAS_CURL_CFFI:
            self._session = curl_requests.Session(
                impersonate=impersonate,
                verify=self.settings.verify_ssl,
                http_version=2 if self.settings.http2 else 1,
            )
        elif _HAS_HTTPX:
            self._session = httpx.Client(
                http2=self.settings.http2,
                verify=self.settings.verify_ssl,
                timeout=self.settings.timeout,
                follow_redirects=True,
            )
        else:
            raise FetcherError("no HTTP backend available; install httpx or curl_cffi")
        self._session_key = key
        return self._session

    def _do_fetch(self, url: str, method: str, session_id: str, **kwargs) -> Any:
        client = self._get_client()
        proxy = self._proxy()
        headers = self._headers(kwargs.pop("headers", None), kwargs.pop("referer", None))
        cookies = self._cookies_for(url, session_id)
        extra_cookies = kwargs.pop("cookies", None)
        if extra_cookies:
            cookies.update(extra_cookies)
        timeout = kwargs.pop("timeout", None) or self.settings.timeout

        start = time.perf_counter()
        if _HAS_CURL_CFFI and isinstance(client, curl_requests.Session):
            resp = client.request(
                method.upper(),
                url,
                headers=headers,
                cookies=cookies or None,
                proxies=proxy or None,
                timeout=timeout,
                **kwargs,
            )
            return self._to_page(
                str(resp.url) or url,
                resp.status_code,
                resp.content,
                dict(resp.headers.items()),
                time.perf_counter() - start,
                session_id,
                request_headers=headers,
            )
        # httpx fallback
        resp = client.request(
            method.upper(), url, headers=headers, cookies=cookies or None,
            proxy=proxy, timeout=timeout, follow_redirects=True, **kwargs,
        )
        return self._to_page(
            str(resp.url) or url,
            resp.status_code,
            resp.content,
            dict(resp.headers.items()),
            time.perf_counter() - start,
            session_id,
            request_headers=headers,
        )

    async def afetch(self, url: str, method: str = "GET", *, session_id: str = "default",
                     raise_on_block: bool = True, **kwargs) -> Any:
        import asyncio

        return await asyncio.to_thread(self._fetch, url, method, session_id=session_id,
                                       raise_on_block=raise_on_block, **kwargs)

    def close(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
