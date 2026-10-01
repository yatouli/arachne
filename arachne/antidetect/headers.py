"""Realistic request-header construction."""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .fingerprints import fingerprint_for

# Headers in the order a real Chrome sends them — order itself is a fingerprint.
_HEADER_ORDER = [
    "accept",
    "accept-language",
    "accept-encoding",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-fetch-user",
    "upgrade-insecure-requests",
    "user-agent",
]


def build_headers(
    impersonate: Optional[str] = None,
    *,
    user_agent: Optional[str] = None,
    locale: Optional[str] = None,
    timezone: Optional[str] = None,
    viewport: Optional[dict[str, int]] = None,
    extra: Optional[Mapping[str, str]] = None,
    referer: Optional[str] = None,
    randomize: bool = False,
) -> dict[str, str]:
    """Build an ordered, internally-consistent set of browser headers."""
    fp = fingerprint_for(
        impersonate,
        user_agent=user_agent,
        locale=locale,
        timezone=timezone,
        viewport=viewport,
        randomize=randomize,
    )
    headers: dict[str, str] = {
        "accept": fp.get("accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        "accept-language": fp.get("accept_language", "en-US,en;q=0.9"),
        "accept-encoding": fp.get("accept_encoding", "gzip, deflate, br"),
        "sec-ch-ua": fp.get("sec_ch_ua", ""),
        "sec-ch-ua-mobile": fp.get("sec_ch_ua_mobile", "?0"),
        "sec-ch-ua-platform": fp.get("sec_ch_ua_platform", '"Windows"'),
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": fp.get("user_agent", ""),
    }
    if referer:
        headers["referer"] = referer
    if extra:
        headers.update(dict(extra))
    return _order(headers, _HEADER_ORDER + [k for k in headers if k not in _HEADER_ORDER])


def _order(headers: dict[str, str], order: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key in order:
        if key in headers and headers[key]:
            result[key] = headers[key]
    for key, value in headers.items():
        if key not in result:
            result[key] = value
    return result


def default_user_agent(impersonate: Optional[str] = None) -> str:
    return fingerprint_for(impersonate).get("user_agent", "")
