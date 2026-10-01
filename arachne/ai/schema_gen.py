"""AI-assisted selector/schema generation and extraction.

Two useful operations:

1. :func:`infer_schema` — give the LLM the page's markdown/structure and the
   fields you want; it returns robust CSS selectors as a :class:`Schema`.
2. :func:`extract_fields` — for messy/one-off pages, have the LLM read the
   cleaned markdown directly and return the values as JSON.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

from ..parsing.schema import Field, Schema
from .llm import LLMClient, get_client

_SYSTEM = (
    "You are a precise web-scraping assistant. Reply with valid JSON only — no "
    "markdown fences, no prose. Follow the requested schema exactly."
)


def _parse_json(text: str) -> Any:
    text = text.strip()
    # Strip markdown fences if the model misbehaved.
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fence:
        text = fence.group(1)
    return json.loads(text)


def infer_schema(
    page_or_markdown,
    field_names: list[str],
    *,
    client: Optional[LLMClient] = None,
    container_hint: Optional[str] = None,
) -> Schema:
    """Ask the LLM to write CSS selectors for the requested fields.

    Returns a :class:`Schema` you can reuse (and which survives structure drift
    when combined with adaptive relocation).
    """
    client = client or get_client()
    markdown = _markdown_of(page_or_markdown)
    prompt = (
        "Given the following page content (as Markdown), return a JSON object "
        "mapping each field name to a CSS selector that extracts its value. "
        "Prefer stable selectors (ids, semantic classes, data-* attributes); "
        "for element text use the form 'h1::text'.\n\n"
        f"Fields: {field_names}\n"
        + (f"Repeated-record container (optional): {container_hint}\n" if container_hint else "")
        + "\nReturn exactly: {\"<field>\": \"<css selector>\", ...}\n\n"
        f"Page content:\n{markdown[:12000]}"
    )
    raw = client.complete(prompt, system=_SYSTEM)
    mapping = _parse_json(raw)
    fields = [Field(name=n, selector=mapping.get(n)) for n in field_names]
    return Schema(fields=fields, container=container_hint)


def extract_fields(
    page_or_markdown,
    field_spec: dict[str, str],
    *,
    client: Optional[LLMClient] = None,
) -> dict[str, Any]:
    """Have the LLM extract values directly from cleaned markdown.

    ``field_spec`` maps field name -> short description, e.g.
    ``{"title": "the product title", "price": "the numeric price"}``.
    """
    client = client or get_client()
    markdown = _markdown_of(page_or_markdown)
    spec_json = json.dumps(field_spec, ensure_ascii=False)
    prompt = (
        "Extract the following fields from the page content. Return a single "
        f"JSON object with exactly these keys and their values: {spec_json}. "
        "Omit or null any field that is not present.\n\n"
        f"Page content:\n{markdown[:12000]}"
    )
    raw = client.complete(prompt, system=_SYSTEM)
    return _parse_json(raw)


def _markdown_of(page_or_markdown) -> str:
    markdown = getattr(page_or_markdown, "markdown", None)
    if callable(markdown):
        return markdown()
    if isinstance(page_or_markdown, str):
        return page_or_markdown
    text = getattr(page_or_markdown, "text", None)
    return text or str(page_or_markdown)
