"""Runtime configuration.

``Settings`` is a single flat dataclass that flows through every layer of the
framework. It is deliberately field-based (not a magical global) so each
fetcher / spider / plugin can carry its own configuration and merge overrides.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, asdict
from typing import Any, Optional


@dataclass
class Settings:
    # ---- HTTP transport -------------------------------------------------
    timeout: float = 30.0
    max_retries: int = 3
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504)
    retry_backoff_base: float = 1.5
    verify_ssl: bool = True
    http2: bool = True

    # ---- Anti-detection / fingerprinting --------------------------------
    # curl_cffi impersonation target: chrome110..chrome124, safari17_0, edge101...
    impersonate: str = "chrome124"
    user_agent: Optional[str] = None
    extra_headers: dict[str, str] = field(default_factory=dict)
    browser_type: str = "chromium"  # chromium | firefox | webkit
    headless: bool = True
    viewport: Optional[dict[str, int]] = None  # {"width": 1920, "height": 1080}
    locale: str = "en-US"
    timezone: str = "UTC"
    stealth_patch: bool = True  # strip navigator.webdriver & friends in browser

    # ---- Proxy ----------------------------------------------------------
    proxies: list[str] = field(default_factory=list)
    proxy_rotation: str = "cyclic"  # cyclic | random | none
    proxy_auth: Optional[tuple[str, str]] = None

    # ---- Spider / crawling ---------------------------------------------
    concurrency: int = 8
    download_delay: float = 0.0
    auto_throttle: bool = True
    auto_throttle_start: float = 1.0
    auto_throttle_max: float = 60.0
    robots_obey: bool = False
    max_requests: Optional[int] = None

    # ---- JS reverse engineering -----------------------------------------
    js_engine: str = "auto"  # auto | node | mini_racer | quickjs
    node_path: str = "node"

    # ---- Caching (development mode) --------------------------------------
    cache_responses: bool = False
    cache_dir: str = ".crawl_cache"

    # ---- AI --------------------------------------------------------------
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout: float = 60.0

    # ---- Output ----------------------------------------------------------
    default_encoding: str = "utf-8"

    # ---- Misc -------------------------------------------------------------
    user_agent_rotation: bool = False

    def merge(self, **overrides: Any) -> "Settings":
        """Return a copy with the given fields overridden."""
        data = asdict(self)
        for key, value in overrides.items():
            if key not in data:
                raise TypeError(f"unknown setting {key!r}")
            data[key] = value
        return Settings(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        valid = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in valid})

    @classmethod
    def from_env(cls, prefix: str = "ARACHNE_") -> "Settings":
        """Build settings from environment variables ``ARACHNE_<FIELD>``.

        ``ARACHNE_PROXIES`` accepts a comma-separated list, and booleans accept
        ``1/true/yes/on``.
        """
        data: dict[str, Any] = {}
        for f in fields(cls):
            env_key = prefix + f.name.upper()
            raw = os.environ.get(env_key)
            if raw is None:
                continue
            if f.type is bool or getattr(f.type, "__origin__", None) is bool:
                data[f.name] = raw.strip().lower() in {"1", "true", "yes", "on"}
            elif f.type is int:
                data[f.name] = int(raw)
            elif f.type is float:
                data[f.name] = float(raw)
            elif f.name == "proxies":
                data[f.name] = [p.strip() for p in raw.split(",") if p.strip()]
            else:
                data[f.name] = raw
        return cls(**data)


# A module-level default used by the convenience ``Fetcher.fetch`` API.
default = Settings()
