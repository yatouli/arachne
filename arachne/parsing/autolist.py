"""自动列表检测（无需选择器，适用于大多数列表/卡片页）。

核心思路：遍历 DOM，把每个元素的「同类子元素」分组，找出重复子元素最多的
那个父节点 —— 它就是列表容器，重复的子元素就是列表项。再从每个列表项里
自动提取 链接/标题/图片/文本。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional
from urllib.parse import urljoin

from .selector import clean_text


def _signature(el):
    cls = (el.get("class") or "").strip()
    id_ = (el.get("id") or "").strip()
    # 去掉疑似动态生成的长哈希类名，保留稳定的语义类
    tokens = [c for c in cls.split() if len(c) <= 30 and not _looks_hashy(c)]
    if not tokens and not id_:
        return None  # 无类名/ID 的通用元素不参与分组，避免误判
    return (el.tag, " ".join(tokens[:4]), id_)


def _looks_hashy(cls: str) -> bool:
    return bool(cls) and sum(ch.isdigit() for ch in cls) + sum(ch in "_-" for ch in cls) >= len(cls) * 0.5


def _group_score(items: list) -> float:
    """分数 = 数量 × 内容丰富度（有链接/图片/标题的占比）。"""
    count = len(items)
    link = sum(1 for it in items if it.find(".//a[@href]") is not None) / count
    img = sum(1 for it in items if it.find(".//img") is not None) / count
    heading = sum(
        1 for it in items
        if it.find(".//h1") is not None or it.find(".//h2") is not None or it.find(".//h3") is not None
    ) / count
    richness = 0.4 * link + 0.35 * img + 0.25 * heading
    return count * (1.0 + richness)


def detect_container(root, min_items: int = 3):
    """Return ``(parent, items)`` for the most-repeated, richest sibling group."""
    best = None
    best_score = 0.0
    for parent in root.iter():
        if not isinstance(parent.tag, str):
            continue
        groups: dict[tuple, list] = defaultdict(list)
        for child in parent:
            if isinstance(child.tag, str):
                sig = _signature(child)
                if sig is not None:
                    groups[sig].append(child)
        for items in groups.values():
            if len(items) < min_items:
                continue
            score = _group_score(items)
            if score > best_score:
                best = (parent, items)
                best_score = score
    return best


def _item_info(item, base_url: str) -> dict[str, Any]:
    link = None
    a = item.find(".//a[@href]")
    if a is not None:
        link = urljoin(base_url, a.get("href"))
    img = None
    im = item.find(".//img[@src]")
    if im is not None:
        src = im.get("src")
        if src and not src.startswith("data:"):
            img = urljoin(base_url, src)
    heading = None
    for tag in ("h1", "h2", "h3", "h4"):
        h = item.find(f".//{tag}")
        if h is not None:
            heading = clean_text(" ".join(h.xpath(".//text()")))
            break
    if not heading and a is not None:
        heading = clean_text(" ".join(a.xpath(".//text()")))
    text = clean_text(" ".join(item.xpath(".//text()")))
    return {"title": heading, "url": link, "image": img, "text": text}


def extract_list(page, min_items: int = 3) -> list[dict[str, Any]]:
    """Auto-detect repeating items on a list page and extract their info."""
    found = detect_container(page.selector.root, min_items)
    if found is None:
        return []
    _parent, items = found
    return [_item_info(item, page.url) for item in items]


def extract_item_links(page, min_items: int = 3) -> list[str]:
    """Auto-detect detail links from a list page (for follow-crawling)."""
    links: list[str] = []
    seen = set()
    for item in extract_list(page, min_items):
        url = item.get("url")
        if url and url not in seen:
            seen.add(url)
            links.append(url)
    return links


def suggest_link_regex(page, min_items: int = 3) -> Optional[str]:
    """Suggest a link pattern that distinguishes detail pages from the list page."""
    import re

    links = extract_item_links(page, min_items)
    if not links:
        return None
    # 用第一段的公共前缀作为模式提示（启发式）
    first = links[0]
    path = re.sub(r"https?://[^/]+", "", first)
    # 提取路径里第一段（如 /homeViewLook/xxx 或 /article/xxx）
    m = re.match(r"(/[^/]+/)", path)
    return m.group(1) if m else None
