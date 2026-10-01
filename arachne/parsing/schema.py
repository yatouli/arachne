"""Schema-driven extraction.

Declare *what* you want with :class:`Field`/:class:`Schema` and let Arachne
handle the how: CSS/XPath querying, type coercion, defaults, required-field
validation, nested objects, and repeated-record extraction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .selector import Selector, clean_text

_TYPE_MAP = {
    "str": str,
    "string": str,
    "int": int,
    "integer": int,
    "float": float,
    "bool": bool,
    "boolean": bool,
    "text": str,
    "html": str,
}


def coerce(value: Optional[str], type_: Any) -> Any:
    if value is None:
        return None
    if type_ is bool:
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    if type_ in (int, float):
        # Strip currency symbols, commas, spaces, etc. before parsing.
        import re

        numeric = re.sub(r"[^\d.\-+]", "", value.strip())
        if numeric in ("", "-", "+", "."):
            return None
        try:
            return int(float(numeric)) if type_ is int else float(numeric)
        except ValueError:
            return None
    return value


@dataclass
class Field:
    """A single extracted field."""

    name: str
    selector: Optional[str] = None
    kind: str = "css"  # css | xpath | text
    type: Any = str
    required: bool = False
    default: Any = None
    get_all: bool = False
    attribute: Optional[str] = None
    transform: Optional[Callable[[Any], Any]] = None
    children: Optional[list["Field"]] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Field":
        data = dict(data)
        if "type" in data and isinstance(data["type"], str):
            data["type"] = _TYPE_MAP.get(data["type"], str)
        if "children" in data and data["children"]:
            data["children"] = [Field.from_dict(c) for c in data["children"]]
        return cls(**data)

    def extract(self, scope: Selector) -> Any:
        # Nested object
        if self.children:
            return {child.name: child.extract(scope) for child in self.children}

        value: Any = None
        if self.selector is None:
            value = clean_text(scope.get()) if self.kind in ("css", "xpath") else scope.text()
        elif self.kind == "xpath":
            nodes = scope.xpath(self.selector)
            value = nodes.getall() if self.get_all else nodes.get()
        elif self.kind == "text":
            value = scope.text()
        else:  # css
            nodes = scope.css(self.selector)
            if self.attribute is not None:
                if self.get_all:
                    value = nodes.attrib(self.attribute)
                else:
                    first = nodes.first
                    value = first.attrib(self.attribute) if first is not None else None
            else:
                value = nodes.getall() if self.get_all else nodes.get()

        if value is None:
            value = self.default
        else:
            value = self._post_process(value)

        if value is None and self.required:
            raise ValueError(f"required field {self.name!r} missing")
        return value

    def _post_process(self, value: Any) -> Any:
        if self.get_all:
            value = [self._coerce_one(v) for v in value]
        else:
            value = self._coerce_one(value)
        if self.transform is not None:
            value = self.transform(value)
        return value

    def _coerce_one(self, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return coerce(value, self.type)


@dataclass
class Schema:
    """A named collection of fields, optionally repeated across a container."""

    fields: list[Field] = field(default_factory=list)
    container: Optional[str] = None  # CSS selector delimiting each record

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Schema":
        return cls(
            fields=[Field.from_dict(f) for f in data.get("fields", [])],
            container=data.get("container"),
        )

    def extract(self, page) -> list[dict[str, Any]] | dict[str, Any]:
        """Extract records from a :class:`Page` (or any object with ``.selector``).

        Returns a list of dicts when ``container`` is set, otherwise a single
        dict.
        """
        scope = page.selector
        if self.container:
            records = []
            for item in scope.css(self.container):
                records.append(self._extract_record(item))
            return records
        return self._extract_record(scope)

    def _extract_record(self, scope: Selector) -> dict[str, Any]:
        return {field.name: field.extract(scope) for field in self.fields}

    def __or__(self, other: "Schema") -> "Schema":
        return Schema(fields=self.fields + other.fields, container=self.container)
