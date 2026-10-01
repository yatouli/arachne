"""Fluent CSS/XPath/text/regex selection with adaptive relocation support."""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator, Optional

from parsel import Selector as _ParselSelector

from ..exceptions import ParseError

# Collapse whitespace AND invisible chars (BOM / zero-width) into a single space.
_STRIP_RE = re.compile(r"[\s\ufeff\u200b-\u200f\u2060]+")


def clean_text(text: Optional[str]) -> str:
    """Collapse whitespace and strip, returning '' for None."""
    if text is None:
        return ""
    return _STRIP_RE.sub(" ", text).strip()


def _first_or_none(items: list) -> Optional[Any]:
    return items[0] if items else None


class Selector:
    """A single element wrapper around :class:`parsel.Selector`."""

    __slots__ = ("_sel", "_page")

    def __init__(self, sel: _ParselSelector, page: Optional["Page"] = None):  # noqa: F821
        self._sel = sel
        self._page = page

    # ---- structural -----------------------------------------------------
    @property
    def root(self):
        """The underlying lxml element."""
        return self._sel.root

    @property
    def page(self) -> Optional["Page"]:  # noqa: F821
        return self._page

    # ---- queries --------------------------------------------------------
    def css(self, query: str) -> "SelectorList":
        return SelectorList(self._sel.css(query), page=self._page)

    def xpath(self, query: str) -> "SelectorList":
        return SelectorList(self._sel.xpath(query), page=self._page)

    def re(self, regex: str, flags: int = 0) -> list[str]:
        return re.findall(regex, self._sel.get() or "", flags)

    def re_first(self, regex: str, default: Optional[str] = None, flags: int = 0) -> Optional[str]:
        match = re.search(regex, self._sel.get() or "", flags)
        if match is None:
            return default
        if match.groups():
            return match.group(1)
        return match.group(0)

    # ---- values ---------------------------------------------------------
    def get(self) -> Optional[str]:
        return self._sel.get()

    def text(self) -> str:
        return clean_text(" ".join(self._sel.root.xpath(".//text()")))

    def attrib(self, name: str, default: Optional[str] = None) -> Optional[str]:
        return self._sel.attrib.get(name, default)

    # ---- helpers --------------------------------------------------------
    def tag(self) -> str:
        return getattr(self._sel.root, "tag", "")

    def parent(self) -> Optional["Selector"]:
        parent = self._sel.root.getparent()
        if parent is None:
            return None
        return Selector(_ParselSelector(root=parent), page=self._page)

    def children(self) -> "SelectorList":
        return SelectorList(
            [_ParselSelector(root=child) for child in self._sel.root.iterchildren()],
            page=self._page,
        )

    def find_similar(self, threshold: float = 0.5) -> "SelectorList":
        """Find elements similar to this one across the whole document."""
        from .adaptive import find_similar_elements

        return find_similar_elements(self, threshold=threshold)

    def __repr__(self) -> str:
        return f"<Selector tag={self.tag()!r} text={self.text()[:40]!r}>"


class SelectorList:
    """A list of :class:`Selector` with fluent bulk operations."""

    __slots__ = ("_sels", "_page")

    def __init__(self, sels: list[_ParselSelector], page: Optional["Page"] = None):  # noqa: F821
        self._sels = sels
        self._page = page

    # ---- python protocol ------------------------------------------------
    def __iter__(self) -> Iterator[Selector]:
        for s in self._sels:
            yield Selector(s, page=self._page)

    def __len__(self) -> int:
        return len(self._sels)

    def __bool__(self) -> bool:
        return bool(self._sels)

    def __getitem__(self, index) -> "Selector | SelectorList":
        if isinstance(index, slice):
            return SelectorList(self._sels[index], page=self._page)
        return Selector(self._sels[index], page=self._page)

    def __repr__(self) -> str:
        return f"<SelectorList len={len(self._sels)}>"

    @property
    def first(self) -> Optional[Selector]:
        return Selector(self._sels[0], page=self._page) if self._sels else None

    def items(self) -> Iterator[Selector]:
        return iter(self)

    # ---- queries --------------------------------------------------------
    def css(self, query: str) -> "SelectorList":
        return self._map(lambda s: s.css(query))

    def xpath(self, query: str) -> "SelectorList":
        return self._map(lambda s: s.xpath(query))

    def re(self, regex: str, flags: int = 0) -> list[str]:
        out: list[str] = []
        for s in self._sels:
            out.extend(re.findall(regex, s.get() or "", flags))
        return out

    def re_first(self, regex: str, default: Optional[str] = None, flags: int = 0) -> Optional[str]:
        for s in self._sels:
            match = re.search(regex, s.get() or "", flags)
            if match is not None:
                return match.group(1) if match.groups() else match.group(0)
        return default

    # ---- values ---------------------------------------------------------
    def get(self) -> Optional[str]:
        return _first_or_none(self.getall())

    def getall(self) -> list[str]:
        out: list[str] = []
        for s in self._sels:
            value = s.get()
            if value is not None:
                out.append(value)
        return out

    def text(self, separator: str = "\n") -> str:
        return separator.join(clean_text(" ".join(s.root.xpath(".//text()"))) for s in self._sels)

    def attrib(self, name: str, default: Optional[str] = None) -> list[str]:
        return [s.attrib.get(name, default) for s in self._sels]

    # ---- helpers --------------------------------------------------------
    def _map(self, fn: Callable[[_ParselSelector], "SelectorList"]) -> "SelectorList":
        collected: list[_ParselSelector] = []
        for s in self._sels:
            collected.extend(fn(s)._sels)
        return SelectorList(collected, page=self._page)

    def as_dicts(self, **fields: str) -> list[dict[str, Any]]:
        """Extract named fields from each element.

        ``page.css('.item').as_dicts(title='h2::text', url='a::attr(href)')``
        """
        records: list[dict[str, Any]] = []
        for item in self:
            record: dict[str, Any] = {}
            for key, query in fields.items():
                record[key] = item.css(query).get()
            records.append(record)
        return records

    def similar(self, threshold: float = 0.5) -> "SelectorList":
        """Return elements similar to the first element of this list."""
        from .adaptive import find_similar_elements

        first = self.first
        if first is None:
            return SelectorList([], page=self._page)
        return find_similar_elements(first, threshold=threshold)


def from_text(text: str, base_url: Optional[str] = None) -> Selector:
    """Build a document-level Selector from raw HTML text."""
    if not isinstance(text, str):
        raise ParseError("from_text expects a str, got " + type(text).__name__)
    return Selector(_ParselSelector(text=text, base_url=base_url))
