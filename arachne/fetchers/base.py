"""Shared fetcher base: retries, backoff, proxy rotation, block handling."""

from __future__ import annotations

import time
from dataclasses import fields as _dc_fields
from typing import Any, Optional
from urllib.parse import urlparse

from ..antidetect.challenge import BlockInfo, detect_block
from ..antidetect.proxy import ProxyRotator
from ..antidetect.session import SessionManager
from ..antidetect.throttle import AutoThrottle
from ..config import Settings
from ..exceptions import BlockedError, ChallengeError, FetcherError
from ..log import get_logger
from ..page import Page

logger = get_logger("fetchers")

_SETTING_FIELDS = {f.name for f in _dc_fields(Settings)}


def _split_settings(settings: Optional[Settings], kwargs: dict[str, Any]):
    """Pull Settings fields out of ``kwargs`` so ``Fetcher.fetch(url, impersonate=...)`` works."""
    overrides: dict[str, Any] = {}
    rest: dict[str, Any] = {}
    for key, value in kwargs.items():
        if key in _SETTING_FIELDS:
            overrides[key] = value
        else:
            rest[key] = value
    if settings is None:
        settings = Settings(**overrides) if overrides else Settings()
    elif overrides:
        settings = settings.merge(**overrides)
    return settings, rest


class FetcherBase:
    """Common machinery shared by HTTP, dynamic and stealthy fetchers."""

    name = "base"
    supports_async = False

    def __init__(self, settings: Optional[Settings] = None, **overrides: Any):
        self.settings = (settings or Settings()).merge(**overrides)
        self.session_manager = SessionManager()
        self.proxy_rotator = ProxyRotator(
            self.settings.proxies,
            strategy=self.settings.proxy_rotation,
            proxy_auth=self.settings.proxy_auth,
        )
        self.throttle = AutoThrottle(
            start_delay=self.settings.auto_throttle_start,
            max_delay=self.settings.auto_throttle_max,
        )
        self._sleep = time.sleep

    # ---- helpers --------------------------------------------------------
    def _headers(self, extra: Optional[dict] = None, referer: Optional[str] = None) -> dict:
        from ..antidetect.headers import build_headers

        merged = dict(self.settings.extra_headers)
        if extra:
            merged.update(extra)
        return build_headers(
            self.settings.impersonate,
            user_agent=self.settings.user_agent,
            locale=self.settings.locale or None,
            timezone=self.settings.timezone or None,
            viewport=self.settings.viewport,
            extra=merged or None,
            referer=referer,
            randomize=self.settings.user_agent_rotation,
        )

    def _proxy(self) -> Optional[str]:
        if not self.proxy_rotator:
            return None
        return self.proxy_rotator.next()

    def _cookies_for(self, url: str, session_id: str) -> dict[str, str]:
        return self.session_manager.cookies_for(url, session_id)

    def _store_cookies(self, url: str, headers: dict[str, str], session_id: str) -> None:
        store = self.session_manager.store(session_id)
        store.update_from_response(url, headers)

    def _to_page(self, url: str, status: int, content: bytes, headers: dict, duration: float,
                 session_id: str, captured_xhr=None, **meta) -> Page:
        self._store_cookies(url, headers, session_id)
        return Page(
            url=url,
            status_code=status,
            content=content,
            headers=headers,
            cookies=self.session_manager.cookies_for(url, session_id),
            duration=duration,
            captured_xhr=captured_xhr,
            **meta,
        )

    # ---- fetch orchestration --------------------------------------------
    @classmethod
    def fetch(cls, url: str, method: str = "GET", *, settings: Optional[Settings] = None,
              session_id: str = "default", raise_on_block: bool = True,
              stealth_fallback: bool = False, **kwargs: Any) -> Page:
        """One-shot fetch convenience: ``Fetcher.fetch(url, impersonate="chrome124")``.

        Any ``Settings`` field may be passed directly (e.g. ``proxies``,
        ``headless``, ``timeout``); the rest are forwarded to the request.
        """
        settings, kwargs = _split_settings(settings, kwargs)
        instance = cls(settings)
        try:
            return instance._fetch(
                url, method, session_id=session_id, raise_on_block=raise_on_block,
                stealth_fallback=stealth_fallback, **kwargs,
            )
        finally:
            instance.close()

    def _fetch(self, url: str, method: str = "GET", *, session_id: str = "default",
               raise_on_block: bool = True, stealth_fallback: bool = False,
               **kwargs: Any) -> Page:
        """Fetch ``url`` synchronously with retries, backoff and block handling."""
        attempts = max(1, self.settings.max_retries + 1)
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                page = self._do_fetch(url, method, session_id=session_id, **kwargs)
                block = detect_block(page)
                if block.blocked:
                    self.throttle.report_block(url)
                    self.proxy_rotator.report_failure()
                    if attempt < attempts - 1:
                        retry_after = self._retry_after(page)
                        logger.debug(
                            "[%s] blocked (%s) on %s; retrying %d/%d",
                            self.name, block.kind, url, attempt + 2, attempts,
                        )
                        self._backoff(attempt, retry_after)
                        continue
                    if stealth_fallback:
                        fallback = self._stealth_fallback(url, session_id=session_id, **kwargs)
                        if fallback is not None and not detect_block(fallback).blocked:
                            return fallback
                    if raise_on_block:
                        raise self._blocked_exception(block, url)
                return page
            except (FetcherError, BlockedError):
                raise
            except Exception as exc:  # network / transport errors
                last_error = exc
                if attempt < attempts - 1:
                    logger.debug("[%s] error on %s: %s; retrying", self.name, url, exc)
                    self._backoff(attempt, None)
                    continue
        raise FetcherError(f"fetch failed after {attempts} attempts: {last_error}")

    def _retry_after(self, page: Page) -> Optional[float]:
        raw = (page.headers or {}).get("retry-after")
        if raw is None:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _backoff(self, attempt: int, retry_after: Optional[float]) -> None:
        if retry_after:
            delay = retry_after
        else:
            delay = self.settings.retry_backoff_base ** attempt
        self._sleep(min(delay, 30.0))

    def _blocked_exception(self, block: BlockInfo, url: str) -> BlockedError:
        msg = f"blocked by {block.kind}: {block.reason}"
        if block.kind in {"cloudflare", "challenge", "captcha"}:
            return ChallengeError(msg, kind=block.kind, url=url)
        return BlockedError(msg, kind=block.kind, url=url)

    def _stealth_fallback(self, url: str, session_id: str, **kwargs) -> Optional[Page]:
        """Escalate to a stealth browser; subclasses can override."""
        from .stealth import StealthyFetcher

        try:
            stealth = StealthyFetcher(self.settings)
            return stealth._fetch(url, session_id=session_id, raise_on_block=False, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[%s] stealth fallback failed: %s", self.name, exc)
            return None

    # ---- to implement ----------------------------------------------------
    def _do_fetch(self, url: str, method: str, session_id: str, **kwargs) -> Page:
        raise NotImplementedError

    def close(self) -> None:
        """Release resources (browsers, pools)."""
