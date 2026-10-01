"""XHR / API-endpoint discovery without touching the browser.

Modern sites ship their data as JSON inside the HTML (``__NEXT_DATA__``,
``__INITIAL_STATE__``, ``window.__NUXT__``) or fetch it from XHR endpoints.
These helpers surface those endpoints and payloads so you can hit the API
directly instead of scraping rendered DOM.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

_URL_RE = re.compile(r"https?://[^\s\"'<>\\]+|/api/[^\s\"'<>\\]+|/[a-zA-Z0-9_./-]+\.json[^\s\"'<>\\]*", re.I)

_STATE_KEYS = [
    "__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "__APOLLO_STATE__",
    "__PRELOADED_STATE__", "window.__DATA__", "window.__INITIAL_DATA__",
    "application/json",
]

_PATH_HINTS = re.compile(r"\.(json|graphql|ajax|api)|/api/|/v[0-9]+/|_next/data", re.I)


def discover_api_endpoints(text: str, base_url: Optional[str] = None) -> list[str]:
    """Return unique API-looking URLs/paths found in HTML or JS text."""
    found: set[str] = set()
    for match in _URL_RE.findall(text):
        candidate = match.rstrip(".,;)]}")
        if not _PATH_HINTS.search(candidate):
            continue
        if base_url and not candidate.startswith("http"):
            candidate = urljoin(base_url, candidate)
        found.add(candidate)
    return sorted(found)


def discover_all_urls(text: str, base_url: Optional[str] = None) -> list[str]:
    """Return every absolute URL found (not just API-looking ones)."""
    found: set[str] = set()
    for match in re.findall(r"https?://[^\s\"'<>\\]+", text):
        candidate = match.rstrip(".,;)]}")
        found.add(candidate)
    return sorted(found)


def find_embedded_state(page_or_html) -> dict[str, Any]:
    """Extract common embedded-JSON state blobs from a page or HTML string."""
    html = _html_of(page_or_html)
    state: dict[str, Any] = {}
    for key in _STATE_KEYS:
        for match in re.finditer(re.escape(key) + r"\s*[:=]\s*", html):
            value = _parse_json_after(html, match.end())
            if value is not None:
                state[key] = value
                break
    # Also try raw <script type="application/json"> blocks
    for i, block in enumerate(re.findall(
        r'<script[^>]+type=["\']application/json["\'][^>]*>(.*?)</script>', html, re.I | re.S
    )):
        try:
            state[f"__script_json_{i}"] = json.loads(block)
        except json.JSONDecodeError:
            pass
    return state


def _html_of(page_or_html) -> str:
    text = getattr(page_or_html, "text", None)
    if text is not None:
        return text
    return str(page_or_html)


def _parse_json_after(text: str, start: int) -> Optional[Any]:
    """Parse a balanced JSON value starting at ``start``."""
    i = start
    while i < len(text) and text[i] in " \t\r\n=":
        i += 1
    if i >= len(text) or text[i] not in "[{":
        return None
    opener = text[i]
    closer = "]" if opener == "[" else "}"
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        ch = text[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[i : j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def endpoint_of(xhr) -> str:
    """Normalize a :class:`CapturedResponse` (or url string) to its path."""
    url = getattr(xhr, "url", xhr)
    return urlparse(str(url)).path
