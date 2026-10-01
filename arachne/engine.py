"""The high-level Arachne engine: fetch + auto-match plugins by URL."""

from __future__ import annotations

from typing import Any, Optional

from .config import Settings
from .fetchers.http import Fetcher
from .log import get_logger
from .page import Page
from .plugins.base import SitePlugin
from .plugins.registry import PluginRegistry, default_registry, load_all

logger = get_logger("engine")


class Arachne:
    """One object that wires plugins, fetchers and settings together.

    ::

        arachne = Arachne(plugin_dirs=["plugins"])
        items = arachne.scrape("https://news.ycombinator.com")
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        registry: Optional[PluginRegistry] = None,
        plugin_dirs: Optional[list[str]] = None,
    ):
        self.settings = settings or Settings()
        self.registry = registry or default_registry
        self._fetchers: dict[str, Any] = {}
        if plugin_dirs:
            load_all(self.registry, directories=plugin_dirs)

    # ---- plugins --------------------------------------------------------
    @property
    def plugins(self) -> list[type[SitePlugin]]:
        return self.registry.all()

    def register(self, plugin_cls, name: Optional[str] = None):
        self.registry.register(plugin_cls, name)
        return plugin_cls

    def match_plugin(self, url: str) -> Optional[type[SitePlugin]]:
        return self.registry.match(url)

    # ---- fetching -------------------------------------------------------
    def _fetcher_for(self, kind: Optional[str]):
        kind = kind or "http"
        if kind not in self._fetchers:
            if kind == "dynamic":
                from .fetchers.dynamic import DynamicFetcher

                self._fetchers[kind] = DynamicFetcher(self.settings)
            elif kind == "stealth":
                from .fetchers.stealth import StealthyFetcher

                self._fetchers[kind] = StealthyFetcher(self.settings)
            else:
                self._fetchers[kind] = Fetcher(self.settings)
        return self._fetchers[kind]

    def fetch(self, url: str, *, fetcher: Optional[str] = None, **kwargs) -> Page:
        return self._fetcher_for(fetcher)._fetch(url, **kwargs)

    # ---- scraping -------------------------------------------------------
    def scrape(self, url: str, *, fetcher: Optional[str] = None, **kwargs) -> Any:
        """Fetch ``url`` and, if a plugin matches, parse it into structured data.

        Returns the parsed items when a plugin matched, otherwise the raw Page.
        """
        plugin_cls = self.match_plugin(url)
        request_ctx: dict[str, Any] = {
            "headers": kwargs.pop("headers", None),
            "params": kwargs.pop("params", None),
        }
        plugin = plugin_cls() if plugin_cls else None
        if plugin is not None:
            plugin.before_fetch(url, request_ctx)
        kind = fetcher or (plugin_cls.fetcher if plugin_cls else "http")
        page = self._fetcher_for(kind)._fetch(
            url,
            headers=request_ctx["headers"],
            params=request_ctx["params"],
            **kwargs,
        )
        if plugin is not None:
            return plugin.parse(page)
        return page

    def close(self) -> None:
        for fetcher in self._fetchers.values():
            try:
                fetcher.close()
            except Exception:  # noqa: BLE001
                pass
        self._fetchers.clear()

    def __enter__(self) -> "Arachne":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
