"""Anti-bot block & challenge detection.

Given a fetched page, these heuristics classify *why* it might be blocked so
the framework can pick a countermeasure (retry with a fresh fingerprint, switch
proxy, solve a JS challenge, or fall back to a stealth browser).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TITLE_PATTERNS = [
    (re.compile(r"just a moment|attention required|checking your browser", re.I), "cloudflare"),
    (re.compile(r"verify you are human|are you a robot|not a robot", re.I), "captcha"),
    (re.compile(r"access denied|request blocked|you have been blocked", re.I), "forbidden"),
    (re.compile(r"too many requests|rate limit", re.I), "rate_limit"),
    (re.compile(r"enable javascript|please enable js", re.I), "js_required"),
    (re.compile(r"captcha|robot check|security check", re.I), "captcha"),
]

_CHALLENGE_HOSTS = [
    "challenges.cloudflare.com",   # Turnstile
    "hcaptcha.com",                # hCaptcha
    "google.com/recaptcha",        # reCAPTCHA
    "recaptcha.net",
    "geo.captcha-delivery.com",    # DataDome
]

# Bodies that only a challenge page would contain. Kept deliberately narrow:
# bare script references (e.g. Cloudflare's "challenge-platform" precursor, or
# a reCAPTCHA/hCaptcha script) appear on millions of NON-blocking pages, so they
# must not be treated as a block.
_CHALLENGE_MARKERS = [
    "cf-turnstile",  # the actual Turnstile widget <div class="cf-turnstile">
    "cf_chl_opt",    # Cloudflare challenge internals
]


@dataclass
class BlockInfo:
    blocked: bool
    kind: str = "none"  # cloudflare | captcha | rate_limit | forbidden | js_required | challenge
    reason: str = ""
    score: float = 0.0

    def __bool__(self) -> bool:
        return self.blocked


def detect_block(page) -> BlockInfo:
    """Classify a :class:`Page` (or any object with ``url/status/headers/text``)."""
    url = getattr(page, "url", "")
    status = getattr(page, "status_code", 200)
    headers = {k.lower(): v for k, v in (getattr(page, "headers", {}) or {}).items()}
    text = getattr(page, "text", "") or ""

    reasons: list[tuple[float, str, str]] = []

    # 1. Status code signals
    if status == 403:
        reasons.append((0.7, "forbidden", "HTTP 403"))
    elif status == 429:
        reasons.append((0.8, "rate_limit", "HTTP 429 too many requests"))
    elif status in (503, 502):
        reasons.append((0.3, "rate_limit", f"HTTP {status}"))

    # 2. Header signals
    if "cf-mitigated" in headers or headers.get("server") == "cloudflare":
        if status == 403:
            reasons.append((0.6, "cloudflare", "Cloudflare mitigation header"))
    if "x-datadome" in headers:
        reasons.append((0.7, "captcha", "DataDome challenge header"))
    if "retry-after" in headers and status == 429:
        reasons.append((0.9, "rate_limit", "Retry-After present with 429"))

    # 3. Title text
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    if title:
        title_text = title.group(1)
        for pattern, kind in _TITLE_PATTERNS:
            if pattern.search(title_text):
                reasons.append((0.75, kind, f"title: {title_text.strip()[:60]}"))
                break

    # 4. Challenge iframes / widgets in the body. Require an actual <iframe>
    #    embedding the challenge host (a script src is NOT a challenge).
    body = text.lower()
    for host in _CHALLENGE_HOSTS:
        if re.search(r"<iframe[^>]*" + re.escape(host), body):
            reasons.append((0.85, "captcha", f"challenge iframe: {host}"))
    for marker in _CHALLENGE_MARKERS:
        if marker in body:
            reasons.append((0.6, "challenge", f"marker: {marker}"))

    # 5. Tiny page with "enable javascript"
    if len(text) < 500 and re.search(r"enable javascript|javascript is required", text, re.I):
        reasons.append((0.5, "js_required", "tiny JS-required page"))

    if not reasons:
        return BlockInfo(False)

    # Highest-scoring reason wins.
    score, kind, reason = max(reasons, key=lambda r: r[0])
    return BlockInfo(True, kind=kind, reason=reason, score=score)
