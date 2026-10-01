"""Anti-detection (反反爬) package."""

from .challenge import BlockInfo, detect_block
from .fingerprints import (
    BROWSER_PROFILES,
    DEFAULT_IMPERSONATE,
    fingerprint_for,
    get_profile,
    is_supported,
    random_profile_name,
    supported_impersonates,
)
from .headers import build_headers, default_user_agent
from .proxy import ProxyRotator, normalize_proxy, parse_proxy
from .session import CookieStore, SessionManager
from .throttle import AutoThrottle

__all__ = [
    "BlockInfo",
    "detect_block",
    "BROWSER_PROFILES",
    "DEFAULT_IMPERSONATE",
    "fingerprint_for",
    "get_profile",
    "is_supported",
    "random_profile_name",
    "supported_impersonates",
    "build_headers",
    "default_user_agent",
    "ProxyRotator",
    "normalize_proxy",
    "parse_proxy",
    "CookieStore",
    "SessionManager",
    "AutoThrottle",
]
