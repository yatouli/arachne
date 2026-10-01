"""Request object for the spider framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Request:
    """A unit of work for the spider scheduler."""

    url: str
    callback: Optional[Callable] = None
    method: str = "GET"
    headers: Optional[dict[str, str]] = None
    cookies: Optional[dict[str, str]] = None
    params: Optional[dict[str, Any]] = None
    data: Any = None
    json: Any = None
    session_id: str = "default"
    #: Override the fetcher for this request: "http" | "dynamic" | "stealth".
    fetcher: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)
    dont_filter: bool = False
    priority: int = 0
    errback: Optional[Callable] = None

    def replace(self, **changes) -> "Request":
        data = {k: getattr(self, k) for k in self.__dataclass_fields__}
        data.update(changes)
        return Request(**data)

    def __lt__(self, other: "Request") -> bool:
        # PriorityQueue pops smallest first; higher priority should come first.
        return self.priority > other.priority

    def __repr__(self) -> str:
        return f"<Request {self.method} {self.url}>"
