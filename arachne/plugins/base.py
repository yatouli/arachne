"""Site plugin base class and registration decorator.

A *site plugin* encapsulates everything needed to scrape one kind of website:
which URLs it matches, how to fetch it, and how to turn the page into
structured data. Write a subclass, drop it in a plugins directory (or register
it as an entry point), and the framework will auto-select it by URL.

Example::

    from arachne.plugins import SitePlugin, plugin

    @plugin
    class HackerNewsPlugin(SitePlugin):
        name = "hackernews"
        domains = ["news.ycombinator.com"]

        def parse(self, page):
            return page.css(".athing").as_dicts(
                title=".titleline a::text",
                url=".titleline a::attr(href)",
                score=".score::text",
            )
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional
from urllib.parse import urlparse


class SitePlugin(ABC):
    """Base class for per-site scraping plugins."""

    #: Unique plugin name.
    name: ClassVar[str] = ""
    #: Domains this plugin handles (case-insensitive, substring match on host).
    domains: ClassVar[list[str]] = []
    #: Additional regex patterns matched against the full URL.
    url_patterns: ClassVar[list[str]] = []
    #: Higher priority wins when several plugins match the same URL.
    priority: ClassVar[int] = 0
    #: Default fetcher: "http" | "dynamic" | "stealth".
    fetcher: ClassVar[str] = "http"
    #: Optional docstring shown by ``arachne plugins``.
    description: ClassVar[str] = ""

    @classmethod
    def match(cls, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        for domain in cls.domains:
            d = domain.lower().lstrip(".")
            if host == d or host.endswith("." + d):
                return True
        for pattern in cls.url_patterns:
            if re.search(pattern, url):
                return True
        return False

    def before_fetch(self, url: str, request: dict[str, Any]) -> None:
        """Hook to mutate the outgoing request (headers, params, ...)."""

    @abstractmethod
    def parse(self, page) -> Any:
        """Turn a :class:`Page` into structured data (dict or list of dicts)."""
        raise NotImplementedError

    # Convenience for returning items from a spider callback.
    def items(self, page) -> list[dict[str, Any]]:
        result = self.parse(page)
        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return list(result)

    def __repr__(self) -> str:
        return f"<SitePlugin {self.name!r} domains={self.domains}>"


def plugin(cls=None, *, name: Optional[str] = None, register: bool = True):
    """Decorator to register a :class:`SitePlugin` subclass in the default registry.

    Usage::

        @plugin
        class MySite(SitePlugin): ...

        # or with an explicit name:
        @plugin(name="my_site")
        class MySite(SitePlugin): ...
    """

    def wrap(klass):
        if not issubclass(klass, SitePlugin):
            raise TypeError("@plugin can only decorate SitePlugin subclasses")
        if name:
            klass.name = name
        if not klass.name:
            klass.name = klass.__name__
        if register:
            from .registry import default_registry

            default_registry.register(klass)
        return klass

    if cls is None:
        return wrap
    return wrap(cls)
