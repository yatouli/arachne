"""The unified ``Page`` result object returned by every fetcher."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from typing import Any, Optional
from urllib.parse import urljoin

from .parsing.selector import Selector, SelectorList, from_text

_BLOCK_TAGS = {
    "p", "div", "section", "article", "header", "footer", "nav", "main", "aside",
    "figure", "figcaption", "blockquote", "pre", "hr", "table", "ul", "ol", "li",
    "h1", "h2", "h3", "h4", "h5", "h6", "form", "fieldset", "details", "summary",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "title", "meta", "link"}


@dataclass
class CapturedResponse:
    """An XHR/fetch response captured while a page loaded."""

    url: str
    method: str = "GET"
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""  # decoded text body

    def json(self) -> Any:
        import json

        return json.loads(self.body) if self.body else None


class Page:
    """A fetched page: raw content, metadata, and a fluent selection API."""

    def __init__(
        self,
        url: str,
        status_code: int = 200,
        *,
        content: bytes | str = b"",
        headers: Optional[dict[str, str]] = None,
        cookies: Optional[dict[str, str]] = None,
        encoding: Optional[str] = None,
        duration: float = 0.0,
        request_headers: Optional[dict[str, str]] = None,
        captured_xhr: Optional[list[CapturedResponse]] = None,
        **meta: Any,
    ):
        self.url = url
        self.status_code = status_code
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})
        self.duration = duration
        self.request_headers = dict(request_headers or {})
        self.captured_xhr: list[CapturedResponse] = list(captured_xhr or [])
        self.meta: dict[str, Any] = dict(meta)
        self._content = content.encode("utf-8") if isinstance(content, str) else bytes(content)
        self._encoding = encoding
        self._text: Optional[str] = None
        self._selector: Optional[Selector] = None

    # ---- content --------------------------------------------------------
    @property
    def content(self) -> bytes:
        return self._content

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self._content.decode(self.encoding, errors="replace")
        return self._text

    @property
    def encoding(self) -> str:
        if self._encoding is None:
            self._encoding = _detect_encoding(self.headers, self._content)
        return self._encoding

    @property
    def selector(self) -> Selector:
        if self._selector is None:
            self._selector = from_text(self.text, base_url=self.url)
            self._selector._page = self  # type: ignore[attr-defined]
        return self._selector

    # ---- selection API ---------------------------------------------------
    def css(self, query: str) -> SelectorList:
        return self.selector.css(query)

    def xpath(self, query: str) -> SelectorList:
        return self.selector.xpath(query)

    def re(self, regex: str, flags: int = 0) -> list[str]:
        return self.selector.re(regex, flags=flags)

    def re_first(self, regex: str, default: Optional[str] = None, flags: int = 0) -> Optional[str]:
        return self.selector.re_first(regex, default=default, flags=flags)

    def text_content(self) -> str:
        """Visible text of the whole page, whitespace-normalized."""
        from .parsing.selector import clean_text

        return clean_text(" ".join(self.selector.root.xpath(".//text()")))

    def markdown(self) -> str:
        """Render the page as clean, LLM-ready Markdown."""
        return html_to_markdown(self.text, base_url=self.url)

    def readable(self) -> dict:
        """Auto-extract the main article: title/content/image/author/date."""
        from .parsing.readability import extract

        return extract(self)

    def list_items(self, min_items: int = 3) -> list[dict]:
        """Auto-detect repeating list items and extract their info."""
        from .parsing.autolist import extract_list

        return extract_list(self, min_items)

    def is_blocked(self) -> bool:
        """Heuristic: does this page look like an anti-bot block page?"""
        from .antidetect.challenge import detect_block

        return detect_block(self).blocked

    def __repr__(self) -> str:
        return f"<Page url={self.url!r} status={self.status_code} bytes={len(self._content)}>"


def _detect_encoding(headers: dict[str, str], content: bytes) -> str:
    ctype = headers.get("content-type", "")
    match = re.search(r"charset=([\w-]+)", ctype, re.IGNORECASE)
    if match:
        return match.group(1)
    # BOM sniffing
    if content.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return "utf-16"
    return "utf-8"


# --------------------------------------------------------------------------
# Minimal, dependency-free HTML -> Markdown converter.
# --------------------------------------------------------------------------
def html_to_markdown(html: str, base_url: Optional[str] = None) -> str:
    from lxml import etree

    try:
        root = etree.HTML(html)
    except etree.ParserError:
        return html
    if root is None:
        return ""
    body = root.find(".//body")
    node = body if body is not None else root
    out: list[str] = []
    _walk(node, base_url or "", out)
    text = "\n".join(out)
    # Collapse 3+ blank lines into 2
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _walk(node, base_url: str, out: list[str], in_pre: bool = False) -> None:
    tag = (node.tag or "").lower() if isinstance(node.tag, str) else ""
    if tag in _SKIP_TAGS:
        return

    if tag == "pre":
        out.append("```")
        out.append((node.text or "") + "".join(node.itertext()) )
        out.append("```")
        out.append("")
        return
    if tag == "code" and not in_pre:
        out.append(f"`{node.text or ''}`")
        return

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        level = int(tag[1])
        out.append(f"{'#' * level} {_inline(node, base_url)}")
        out.append("")
        return
    if tag == "hr":
        out.append("---")
        out.append("")
        return
    if tag == "br":
        out.append("  ")
        return
    if tag == "img":
        src = node.get("src", "")
        alt = node.get("alt", "")
        if src:
            src = urljoin(base_url, src)
            out.append(f"![{alt}]({src})")
        return
    if tag == "a":
        href = node.get("href", "")
        if href:
            href = urljoin(base_url, href)
            out.append(f"[{_inline(node, base_url)}]({href})")
        else:
            out.append(_inline(node, base_url))
        return
    if tag in ("strong", "b"):
        out.append(f"**{_inline(node, base_url)}**")
        return
    if tag in ("em", "i"):
        out.append(f"*{_inline(node, base_url)}*")
        return
    if tag == "blockquote":
        inner: list[str] = []
        for child in node:
            _walk(child, base_url, inner, in_pre)
        out.extend("> " + line for line in "\n".join(inner).splitlines())
        out.append("")
        return
    if tag == "li":
        text = _inline(node, base_url)
        out.append(f"- {text}")
        return
    if tag in ("tr",):
        cells = [c for c in node if (c.tag or "").lower() in ("td", "th")]
        out.append("| " + " | ".join(_inline(c, base_url) for c in cells) + " |")
        return

    # Recurse into children
    for child in node:
        _walk(child, base_url, out, in_pre)

    if tag in _BLOCK_TAGS:
        out.append("")
    else:
        tail = (node.tail or "").strip()
        if tail:
            out.append(tail)


def _inline(node, base_url: str) -> str:
    parts: list[str] = []
    if node.text:
        parts.append(node.text.strip())
    for child in node:
        tag = (child.tag or "").lower() if isinstance(child.tag, str) else ""
        if tag == "a":
            href = child.get("href", "")
            href = urljoin(base_url, href) if href else ""
            parts.append(f"[{_inline(child, base_url)}]({href})")
        elif tag in ("strong", "b"):
            parts.append(f"**{_inline(child, base_url)}**")
        elif tag in ("em", "i"):
            parts.append(f"*{_inline(child, base_url)}*")
        elif tag == "code":
            parts.append(f"`{_inline(child, base_url)}`")
        elif tag == "img":
            src = child.get("src", "")
            src = urljoin(base_url, src) if src else ""
            parts.append(f"![{child.get('alt', '')}]({src})")
        elif tag == "br":
            parts.append(" ")
        else:
            parts.append(_inline(child, base_url))
        if child.tail:
            parts.append(child.tail.strip())
    return " ".join(p for p in parts if p)
