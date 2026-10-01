"""自动正文提取（无需选择器，适用于大多数新闻 / 博客 / 文章页）。

类似 Readability 的启发式算法：给正文节点打分（文本长度 + 段落数 +
标点密度，并惩罚链接密度和导航/页脚类名），取最高分的节点作为正文。
"""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import urljoin

from .selector import clean_text

_NAV_HINTS = re.compile(
    r"nav|menu|footer|header|sidebar|comment|advert|ad-|share|related|recommend"
    r"|breadcrumb|pagination|toolbar|widget|copyright|catalog|hot|tag-|list-",
    re.I,
)
_CONTENT_HINTS = re.compile(r"article|content|post|entry|main|detail|text|body|read", re.I)

_SKIP_TAGS = {"script", "style", "noscript", "template", "svg", "head", "meta", "link",
              "iframe", "form", "button", "input", "select", "option", "textarea"}


def _visible_text(node) -> str:
    """Text of ``node`` excluding script/style/noscript descendants."""
    parts = node.xpath(
        ".//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]"
    )
    return clean_text(" ".join(parts))

_DATE_META = ["article:published_time", "datePublished", "pubdate", "date"]
_AUTHOR_META = ["article:author", "author", "byline"]


def extract(page) -> dict[str, Any]:
    """Extract ``title/content/image/author/date/url`` from a page."""
    root = page.selector.root
    title = _title(page)
    node = _main_content_node(root)
    content = _visible_text(node) if node is not None else ""
    image = _image(page, node)
    author = _author(page)
    date = _date(page, root)
    return {
        "title": title,
        "content": content,
        "image": image,
        "author": author,
        "date": date,
        "url": page.url,
    }


def _meta(page, names: list[str]) -> Optional[str]:
    for name in names:
        for val in page.css(f'meta[property="{name}"]::attr(content), meta[name="{name}"]::attr(content)').getall():
            if val:
                return val.strip()
    return None


def _title(page) -> str:
    h1 = page.css("h1::text").get()
    if h1 and h1.strip():
        return h1.strip()
    og = _meta(page, ["og:title", "twitter:title"])
    if og:
        return og
    return (page.css("title::text").get() or "").strip()


def _score(node) -> float:
    text = _visible_text(node)
    if len(text) < 60:
        return 0.0
    p_count = len(node.xpath(".//p"))
    commas = text.count("，") + text.count(",") + text.count("。")
    link_text = clean_text(" ".join(node.xpath(".//a//text()")))
    link_density = len(link_text) / max(1.0, len(text))

    score = len(text) * (1.0 - 0.7 * link_density) + p_count * 40.0 + commas * 8.0

    cls_id = f"{node.get('class') or ''} {node.get('id') or ''}"
    if _CONTENT_HINTS.search(cls_id):
        score *= 1.3
    if _NAV_HINTS.search(cls_id):
        score *= 0.15
    return score


def _main_content_node(root):
    best_node = None
    best_score = 0.0
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        if node.tag.lower() in _SKIP_TAGS:
            continue
        score = _score(node)
        if score > best_score:
            best_score = score
            best_node = node

    if best_node is None:
        return None

    # 向上合并：若父节点得分不低，用父节点以包含完整正文
    node = best_node
    parent = node.getparent()
    while parent is not None and isinstance(parent.tag, str):
        parent_score = _score(parent)
        if parent_score >= best_score * 0.6 and len(_visible_text(parent)) <= len(
            _visible_text(node)
        ) * 3:
            node = parent
            parent = node.getparent()
        else:
            break
    return node


def _image(page, node) -> Optional[str]:
    og = _meta(page, ["og:image", "twitter:image"])
    if og:
        return og
    scope = node if node is not None else page.selector.root
    srcs = scope.xpath(".//img//@src")
    for src in srcs:
        if src and not src.startswith("data:"):
            return urljoin(page.url, src)
    return None


def _author(page) -> Optional[str]:
    return _meta(page, _AUTHOR_META)


def _date(page, root) -> Optional[str]:
    meta = _meta(page, _DATE_META)
    if meta:
        return meta
    for time_el in root.xpath(".//time"):
        dt = time_el.get("datetime") or time_el.get("content")
        if dt:
            return dt
    text = clean_text(" ".join(root.xpath(".//text()")))
    m = re.search(r"(20\d{2}[-/年]\d{1,2}[-/月]\d{1,2})", text)
    return m.group(1) if m else None
