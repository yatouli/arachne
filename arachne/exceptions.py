"""Exception hierarchy for Arachne."""

from __future__ import annotations


class ArachneError(Exception):
    """Base class for every Arachne error."""


class FetcherError(ArachneError):
    """A transport / fetching failure (network, timeout, bad status ...)."""


class BlockedError(FetcherError):
    """The request was blocked by anti-bot protection.

    ``kind`` is a machine-readable reason so callers can branch on it, e.g.
    ``"cloudflare"``, ``"captcha"``, ``"rate_limit"``, ``"forbidden"``.
    """

    def __init__(self, message: str, *, kind: str = "blocked", url: str | None = None):
        self.kind = kind
        self.url = url
        super().__init__(message)


class ChallengeError(BlockedError):
    """A JS/anti-bot challenge (Turnstile, interstitial, hCaptcha ...) was hit."""

    def __init__(self, message: str, *, kind: str = "challenge", url: str | None = None):
        super().__init__(message, kind=kind, url=url)


class ParseError(ArachneError):
    """Parsing / selector errors."""


class AdaptiveError(ParseError):
    """Adaptive element relocation failed."""


class JsError(ArachneError):
    """A JS reverse-engineering operation failed."""


class JsEngineUnavailableError(JsError):
    """No JS engine could be loaded (install ``py_mini_racer`` or Node)."""


class PluginError(ArachneError):
    """A plugin failed to load or execute."""


class SpiderError(ArachneError):
    """A spider runtime error."""


class ExportError(ArachneError):
    """An exporter failed."""
