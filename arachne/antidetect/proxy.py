"""Proxy rotation."""

from __future__ import annotations

import itertools
import random
import threading
from typing import Iterator, Optional
from urllib.parse import urlparse, urlunparse


class ProxyRotator:
    """Cycle or randomly sample from a list of proxies.

    Strategies:
      * ``cyclic`` — round-robin in order (deterministic, thread-safe).
      * ``random`` — uniform random each time.
      * ``sticky`` — keep using the same proxy until it fails, then advance.

    Proxies may be given as full URLs (``http://user:pass@host:port``) or bare
    ``host:port``. Authentication embedded in the URL is parsed out and exposed
    separately, since most HTTP clients take it as dedicated params.
    """

    def __init__(
        self,
        proxies: Optional[list[str]] = None,
        strategy: str = "cyclic",
        proxy_auth: Optional[tuple[str, str]] = None,
    ):
        self._proxies = list(proxies or [])
        self._strategy = strategy
        self._proxy_auth = proxy_auth
        self._lock = threading.Lock()
        self._cursor = 0
        self._sticky_index: Optional[int] = 0 if self._proxies else None

    def __len__(self) -> int:
        return len(self._proxies)

    def __bool__(self) -> bool:
        return bool(self._proxies)

    def add(self, proxy: str) -> None:
        with self._lock:
            if proxy not in self._proxies:
                self._proxies.append(proxy)

    @property
    def proxies(self) -> list[str]:
        return list(self._proxies)

    def next(self) -> Optional[str]:
        with self._lock:
            if not self._proxies:
                return None
            if self._strategy == "random":
                return random.choice(self._proxies)
            if self._strategy == "sticky":
                if self._sticky_index is None:
                    self._sticky_index = 0
                return self._proxies[self._sticky_index]
            # cyclic
            proxy = self._proxies[self._cursor % len(self._proxies)]
            self._cursor += 1
            return proxy

    def report_failure(self) -> None:
        """Called when the current proxy failed; advance the sticky cursor."""
        if self._strategy == "sticky" and self._proxies:
            with self._lock:
                self._sticky_index = (self._sticky_index or 0) + 1
                if self._sticky_index >= len(self._proxies):
                    self._sticky_index = 0

    def __iter__(self) -> Iterator[str]:
        if not self._proxies:
            return iter(())
        if self._strategy == "random":
            return (random.choice(self._proxies) for _ in itertools.count())
        return itertools.cycle(self._proxies)


def parse_proxy(proxy: str) -> dict[str, object]:
    """Split a proxy string into scheme/host/port/username/password."""
    if "://" not in proxy:
        proxy = "http://" + proxy
    parsed = urlparse(proxy)
    return {
        "scheme": parsed.scheme or "http",
        "host": parsed.hostname or "",
        "port": parsed.port,
        "username": parsed.username,
        "password": parsed.password,
    }


def normalize_proxy(proxy: str) -> str:
    """Return a canonical ``scheme://host:port`` URL, dropping credentials."""
    info = parse_proxy(proxy)
    host = info["host"]
    port = info["port"]
    netloc = host if port is None else f"{host}:{port}"
    return urlunparse((str(info["scheme"]), netloc, "", "", "", ""))
