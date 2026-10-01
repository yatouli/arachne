"""Response object: a fetched page plus the request that produced it."""

from __future__ import annotations

from typing import Any, Optional

from ..page import Page
from .request import Request


class Response:
    """Wraps a :class:`Page` with its originating :class:`Request`.

    Delegates every attribute it doesn't define to the underlying page, so
    ``response.css(...)``, ``response.url``, ``response.markdown()`` etc. all
    work transparently.
    """

    def __init__(self, request: Request, page: Page):
        self.request = request
        self.page = page

    def __getattr__(self, name: str) -> Any:
        return getattr(self.page, name)

    def follow(
        self,
        url: str,
        callback: Optional[Any] = None,
        *,
        fetcher: Optional[str] = None,
        meta: Optional[dict[str, Any]] = None,
        **kwargs,
    ) -> Request:
        """Build a :class:`Request` for ``url`` (resolved against this page)."""
        from urllib.parse import urljoin

        absolute = urljoin(self.page.url, url)
        return Request(
            absolute,
            callback=callback,
            fetcher=fetcher or self.request.fetcher,
            meta={**(self.request.meta or {}), **(meta or {})},
            session_id=self.request.session_id,
            **kwargs,
        )

    def __repr__(self) -> str:
        return f"<Response {self.page.url!r} status={self.page.status_code}>"
