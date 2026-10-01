"""Parsing package: selectors, adaptive relocation, and schema extraction."""

from .adaptive import ElementFingerprint, build_selector, find_similar_elements, relocate
from .autolist import extract_item_links, extract_list, suggest_link_regex
from .readability import extract as extract_readable
from .schema import Field, Schema
from .selector import Selector, SelectorList, clean_text, from_text

__all__ = [
    "Selector",
    "SelectorList",
    "clean_text",
    "from_text",
    "ElementFingerprint",
    "build_selector",
    "find_similar_elements",
    "relocate",
    "extract_readable",
    "extract_list",
    "extract_item_links",
    "suggest_link_regex",
    "Field",
    "Schema",
]
