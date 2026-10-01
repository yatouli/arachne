"""Adaptive element relocation.

When a site ships a redesign, plain CSS/XPath selectors silently break.
Adaptive parsing keeps a lightweight *fingerprint* of the element you care
about and re-finds the best match in the new DOM using weighted feature
similarity — the same idea that powers Scrapling's smart element tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Iterable, Optional

from .selector import Selector, SelectorList, clean_text


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class ElementFingerprint:
    """A cheap, order-invariant description of a DOM element."""

    tag: str = ""
    id: str = ""
    classes: frozenset[str] = field(default_factory=frozenset)
    attr_names: frozenset[str] = field(default_factory=frozenset)
    text: str = ""
    depth: int = 0
    parent_tag: str = ""

    @classmethod
    def from_element(cls, element) -> "ElementFingerprint":
        root = getattr(element, "root", element)
        tag = (root.tag or "").lower()
        attrib = dict(root.attrib or {})
        classes = frozenset((attrib.get("class", "") or "").split())
        return cls(
            tag=tag,
            id=attrib.get("id", ""),
            classes=classes,
            attr_names=frozenset(attrib.keys()),
            text=clean_text(" ".join(root.xpath(".//text()"))),
            depth=_depth(root),
            parent_tag=(root.getparent().tag or "").lower() if root.getparent() is not None else "",
        )

    def similarity(self, other: "ElementFingerprint") -> float:
        """Weighted similarity in ``[0, 1]``.

        Weights favour the most distinctive, least-brittle signals: ``id`` and
        tag are strong; classes are the workhorse; text and structure break ties.
        """
        score = 0.0
        if self.tag == other.tag and self.tag:
            score += 0.20
        if self.id and self.id == other.id:
            score += 0.30
        score += 0.22 * _jaccard(self.classes, other.classes)
        score += 0.10 * _jaccard(self.attr_names, other.attr_names)
        score += 0.13 * SequenceMatcher(None, self.text, other.text).ratio()
        if self.parent_tag and self.parent_tag == other.parent_tag:
            score += 0.03
        # Depth difference small penalty
        score += 0.02 * max(0.0, 1.0 - abs(self.depth - other.depth) / 10.0)
        return min(1.0, score)


def _depth(root) -> int:
    depth = 0
    node = root
    while node is not None:
        node = node.getparent()
        depth += 1
    return depth


def _document_elements(page_selector: Selector) -> Iterable:
    root = page_selector.root
    return root.iter()


def find_similar_elements(
    source: Selector, threshold: float = 0.5, limit: int = 20
) -> SelectorList:
    """Find elements across the document that resemble ``source``.

    ``source.page`` (if set) provides the document to scan; otherwise the scan
    runs against ``source``'s own root ancestor.
    """
    target_fp = ElementFingerprint.from_element(source)
    page = source.page
    doc_root = page.selector.root if page is not None else _top_root(source.root)
    scored: list[tuple[float, object]] = []
    for element in doc_root.iter():
        if element is source.root:
            continue
        fp = ElementFingerprint.from_element(element)
        score = target_fp.similarity(fp)
        if score >= threshold:
            scored.append((score, element))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return SelectorList(
        [_mk_selector(element, page) for _, element in scored[:limit]], page=page
    )


def relocate(
    page_selector: Selector, fingerprint: ElementFingerprint, threshold: float = 0.5, limit: int = 10
) -> SelectorList:
    """Relocate an element by fingerprint inside ``page_selector``'s document."""
    doc_root = page_selector.root
    scored: list[tuple[float, object]] = []
    for element in doc_root.iter():
        fp = ElementFingerprint.from_element(element)
        score = fingerprint.similarity(fp)
        if score >= threshold:
            scored.append((score, element))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    page = page_selector.page
    return SelectorList(
        [_mk_selector(element, page) for _, element in scored[:limit]], page=page
    )


def _mk_selector(element, page):
    from parsel import Selector as _ParselSelector

    return Selector(_ParselSelector(root=element), page=page)


def _top_root(root):
    node = root
    while node.getparent() is not None:
        node = node.getparent()
    return node


def build_selector(element) -> str:
    """Generate a robust CSS selector for an element (id > classes > tag:nth)."""
    from parsel import Selector as _ParselSelector

    if not isinstance(element, Selector):
        element = Selector(_ParselSelector(root=element))
    root = element.root
    tag = (root.tag or "").lower()
    attrib = dict(root.attrib or {})
    if attrib.get("id"):
        return f"{tag}#{attrib['id']}"
    classes = [c for c in (attrib.get("class", "") or "").split() if c]
    if classes:
        return f"{tag}.{'.'.join(classes)}"
    parent = root.getparent()
    if parent is None:
        return tag
    siblings = list(parent.iterchildren(tag))
    if len(siblings) == 1:
        return tag
    index = siblings.index(root) + 1
    return f"{tag}:nth-of-type({index})"
