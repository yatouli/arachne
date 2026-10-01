"""Link extraction for crawling."""

from __future__ import annotations

import re
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

_EXCLUDED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico", ".css", ".js",
    ".pdf", ".zip", ".gz", ".tar", ".mp4", ".mp3", ".woff", ".woff2", ".ttf",
}


class LinkExtractor:
    """Extract links from a :class:`Response` with allow/deny filtering."""

    def __init__(
        self,
        allow: Optional[Iterable[str]] = None,
        deny: Optional[Iterable[str]] = None,
        restrict_domains: Optional[Iterable[str]] = None,
        restrict_css: Optional[str] = None,
        allow_extensions: Optional[Iterable[str]] = None,
        deny_extensions: Optional[Iterable[str]] = None,
        tags: Iterable[str] = ("a", "area"),
        attrs: Iterable[str] = ("href",),
        canonicalize: bool = True,
        unique: bool = True,
    ):
        self.allow = [re.compile(p) for p in (allow or [])]
        self.deny = [re.compile(p) for p in (deny or [])]
        self.restrict_domains = {d.lower().lstrip(".") for d in (restrict_domains or [])}
        self.restrict_css = restrict_css
        self.allow_extensions = {e.lower() for e in (allow_extensions or [])}
        self.deny_extensions = {
            e.lower() for e in (deny_extensions or []) if e.lower() not in _EXCLUDED_EXTENSIONS
        } | _EXCLUDED_EXTENSIONS
        self.tags = list(tags)
        self.attrs = list(attrs)
        self.canonicalize = canonicalize
        self.unique = unique

    def extract_links(self, response) -> list[str]:
        scope = response.selector
        if self.restrict_css:
            scope = scope.css(self.restrict_css).first or scope
        base_url = response.url
        links: list[str] = []
        seen: set[str] = set()
        for tag in self.tags:
            for el in scope.root.iter(tag):
                for attr in self.attrs:
                    href = el.get(attr)
                    if not href:
                        continue
                    absolute = urljoin(base_url, href.strip())
                    if self.canonicalize:
                        absolute = _canonicalize(absolute)
                    if not absolute or not absolute.startswith(("http://", "https://")):
                        continue
                    if not self._allowed(absolute):
                        continue
                    if self.unique and absolute in seen:
                        continue
                    seen.add(absolute)
                    links.append(absolute)
        return links

    def _allowed(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        if self.restrict_domains:
            if not any(host == d or host.endswith("." + d) for d in self.restrict_domains):
                return False
        ext = urlparse(url).path.lower()
        ext = ext[ext.rfind("."):] if "." in ext else ""
        if ext:
            if self.allow_extensions and ext not in self.allow_extensions:
                return False
            if ext in self.deny_extensions:
                return False
        if any(p.search(url) for p in self.deny):
            return False
        if self.allow and not any(p.search(url) for p in self.allow):
            return False
        return True


def _canonicalize(url: str) -> str:
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if parsed.scheme in ("http", "https") and parsed.port:
        default = 80 if parsed.scheme == "http" else 443
        if parsed.port == default:
            host = parsed.hostname or ""
            netloc = host
    from urllib.parse import urlunparse

    return urlunparse((parsed.scheme, netloc, path, parsed.params, parsed.query, ""))
