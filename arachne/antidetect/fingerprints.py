"""Browser fingerprint presets & generation.

A *consistent* fingerprint matters more than a perfect one: the UA, the
``Sec-CH-UA`` client hints, ``Accept*`` headers, viewport, platform and
timezone must all tell the same story, or anti-bot systems flag the mismatch.
"""

from __future__ import annotations

import random
from typing import Any, Optional

# Keys match curl_cffi's ``impersonate`` targets where possible, so the same
# name can drive both the TLS fingerprint and the header/client-hint profile.
BROWSER_PROFILES: dict[str, dict[str, Any]] = {
    "chrome110": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="110", "Not A(Brand";v="24", "Google Chrome";v="110"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br",
        "platform": "Windows",
        "viewport": {"width": 1920, "height": 1080},
        "os": "win32",
        "device_memory": 8,
        "hardware_concurrency": 8,
    },
    "chrome116": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="116", "Not)A;Brand";v="24", "Google Chrome";v="116"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br",
        "platform": "Windows",
        "viewport": {"width": 1366, "height": 768},
        "os": "win32",
        "device_memory": 4,
        "hardware_concurrency": 8,
    },
    "chrome120": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br, zstd",
        "platform": "Windows",
        "viewport": {"width": 1920, "height": 1080},
        "os": "win32",
        "device_memory": 8,
        "hardware_concurrency": 12,
    },
    "chrome124": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br, zstd",
        "platform": "Windows",
        "viewport": {"width": 1920, "height": 1080},
        "os": "win32",
        "device_memory": 8,
        "hardware_concurrency": 16,
    },
    "chrome131": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "sec_ch_ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br, zstd",
        "platform": "Windows",
        "viewport": {"width": 1920, "height": 1080},
        "os": "win32",
        "device_memory": 8,
        "hardware_concurrency": 16,
    },
    "safari17_0": {
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "sec_ch_ua": '"Not_A Brand";v="8", "Chromium";v="118", "Google Chrome";v="118"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"macOS"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br",
        "platform": "macOS",
        "viewport": {"width": 1440, "height": 900},
        "os": "mac",
        "device_memory": 8,
        "hardware_concurrency": 8,
    },
    "firefox133": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 "
        "Firefox/133.0",
        "sec_ch_ua": '"Firefox";v="133", "Not)A;Brand";v="8", "Chromium";v="133"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8",
        "accept_language": "en-US,en;q=0.5",
        "accept_encoding": "gzip, deflate, br",
        "platform": "Windows",
        "viewport": {"width": 1920, "height": 1080},
        "os": "win32",
        "device_memory": 8,
        "hardware_concurrency": 8,
    },
    "edge101": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/101.0.4951.64 Safari/537.36 Edg/101.0.1210.32",
        "sec_ch_ua": '" Not A;Brand";v="99", "Chromium";v="101", "Microsoft Edge";v="101"',
        "sec_ch_ua_mobile": "?0",
        "sec_ch_ua_platform": '"Windows"',
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept_language": "en-US,en;q=0.9",
        "accept_encoding": "gzip, deflate, br",
        "platform": "Windows",
        "viewport": {"width": 1920, "height": 1080},
        "os": "win32",
        "device_memory": 8,
        "hardware_concurrency": 16,
    },
}

_TIMEZONES = [
    "America/New_York", "America/Chicago", "America/Los_Angeles", "Europe/London",
    "Europe/Berlin", "Europe/Paris", "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore",
    "Australia/Sydney",
]
_LANGUAGES = [
    "en-US,en;q=0.9", "en-GB,en;q=0.9", "en-US,en;q=0.9,fr;q=0.8", "de-DE,de;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9,en;q=0.8", "ja-JP,ja;q=0.9,en;q=0.8",
]


def get_profile(name: str) -> dict[str, Any]:
    """Return a copy of the named browser profile, or an empty dict."""
    profile = BROWSER_PROFILES.get(name)
    return dict(profile) if profile else {}


def fingerprint_for(
    impersonate: Optional[str] = None,
    *,
    user_agent: Optional[str] = None,
    locale: Optional[str] = None,
    timezone: Optional[str] = None,
    viewport: Optional[dict[str, int]] = None,
    randomize: bool = False,
) -> dict[str, Any]:
    """Build a coherent fingerprint dict.

    Falls back to the default profile when ``impersonate`` is unknown. With
    ``randomize=True``, incidental-but-consistent values (language, timezone,
    concurrency) are varied while the UA/client-hints stay aligned.
    """
    profile = get_profile(impersonate or "chrome124") or get_profile("chrome124")
    fp: dict[str, Any] = dict(profile)
    if user_agent:
        fp["user_agent"] = user_agent
    if locale:
        fp["accept_language"] = locale
        fp["locale"] = locale
    else:
        fp["locale"] = fp.get("accept_language", "en-US")
    fp["timezone"] = timezone or fp.get("timezone", "UTC")
    if viewport:
        fp["viewport"] = dict(viewport)
    if randomize:
        fp["accept_language"] = random.choice(_LANGUAGES)
        fp["locale"] = fp["accept_language"].split(",")[0]
        fp["timezone"] = random.choice(_TIMEZONES)
        fp["hardware_concurrency"] = random.choice([4, 8, 12, 16])
    return fp


def random_profile_name() -> str:
    return random.choice(list(BROWSER_PROFILES.keys()))


#: A fingerprint that curl_cffi is all but guaranteed to support.
DEFAULT_IMPERSONATE = "chrome124"


def supported_impersonates() -> list[str]:
    """Return the profile names the installed ``curl_cffi`` can impersonate.

    Falls back to the full curated list when curl_cffi is unavailable. This
    guards against version drift in curl_cffi's supported browser names.
    """
    try:
        from curl_cffi.requests.impersonate import BrowserType

        supported = {browser.value for browser in BrowserType}
    except Exception:  # noqa: BLE001
        return list(BROWSER_PROFILES.keys())
    return [name for name in BROWSER_PROFILES if name in supported]


def is_supported(name: str) -> bool:
    """True if ``name`` is a valid impersonation target for the installed curl_cffi."""
    return name in supported_impersonates()
