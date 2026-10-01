"""Signature function discovery & invocation.

The classic 逆向 flow is:

1. Grab the page's JavaScript.
2. Find the function(s) that compute the ``sign``/``token``/``encrypt`` value.
3. Load the JS into a :class:`JsEngine` and call that function with your payload
   to reproduce the signature — then call the API directly.

These helpers automate steps 2 and 3 as far as is possible without a human.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..log import get_logger
from .engine import JsEngine

logger = get_logger("js.signatures")

_FUNC_DEF_RE = re.compile(
    r"(?:function\s+([A-Za-z_$][\w$]*)\s*\(|"
    r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*function\s*\(|"
    r"([A-Za-z_$][\w$]*)\s*[:=]\s*(?:async\s*)?\([^)]*\)\s*=>)"
)

_SIGNAL_KEYWORDS = [
    "sign", "signature", "token", "encrypt", "decrypt", "cipher", "digest",
    "md5", "sha1", "sha256", "sha512", "hmac", "hash", "aes", "rsa", "genkey",
    "getsign", "makesign", "sig", "x-sign", "x-token", "secret",
]

_HASH_ALGOS = {
    "md5": re.compile(r"\bmd5\b", re.I),
    "sha1": re.compile(r"\bsha-?1\b|sha1", re.I),
    "sha256": re.compile(r"\bsha-?256\b|sha256", re.I),
    "sha512": re.compile(r"\bsha-?512\b|sha512", re.I),
    "hmac": re.compile(r"\bhmac\b|createHmac", re.I),
    "aes": re.compile(r"\bAES\b|createCipher|aes-", re.I),
    "rsa": re.compile(r"\bRSA\b|publicEncrypt|privateEncrypt", re.I),
}


def extract_function_names(js: str) -> list[str]:
    """Return function names declared in the JS source (best-effort)."""
    names: list[str] = []
    seen: set[str] = set()
    for match in _FUNC_DEF_RE.finditer(js):
        name = next((g for g in match.groups() if g), None)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def detect_hash_algorithms(js: str) -> list[str]:
    """Detect which crypto primitives the JS references."""
    return [algo for algo, pattern in _HASH_ALGOS.items() if pattern.search(js)]


def guess_signature_functions(js: str, extra_keywords: Optional[list[str]] = None) -> list[str]:
    """Rank likely signature functions by name signal strength."""
    keywords = _SIGNAL_KEYWORDS + (extra_keywords or [])
    lowered = js.lower()
    scores: dict[str, int] = {}
    for name in extract_function_names(js):
        n = name.lower()
        score = 0
        for kw in keywords:
            if kw == n:
                score += 5
            elif kw in n:
                score += 2
        # Bonus: function is called near string concat/URL building
        if score:
            scores[name] = score
    return [name for name, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)]


@dataclass
class SignatureResult:
    """Outcome of a signature-cracking attempt."""

    function_name: str
    value: Any
    matches: bool = False
    observed: Any = None
    error: Optional[str] = None


@dataclass
class SignatureCracker:
    """Load site JS, locate candidate signers, and test them against a known value."""

    js: str
    engine: JsEngine
    candidates: list[str] = field(default_factory=list)
    _loaded: bool = False

    @classmethod
    def from_page(cls, page_or_html, engine: Optional[JsEngine] = None) -> "SignatureCracker":
        """Build a cracker from a page's inline scripts."""
        from .engine import extract_scripts

        html = getattr(page_or_html, "text", None) or str(page_or_html)
        js = "\n".join(extract_scripts(html))
        engine = engine or JsEngine()
        cracker = cls(js=js, engine=engine)
        cracker.candidates = guess_signature_functions(js)
        return cracker

    def load(self) -> None:
        """Execute the JS so its functions become callable in the engine."""
        if self._loaded or not self.js.strip():
            return
        self.engine.run(self.js)
        self._loaded = True

    def find_candidates(self, extra_keywords: Optional[list[str]] = None) -> list[str]:
        self.candidates = guess_signature_functions(self.js, extra_keywords)
        return self.candidates

    def try_sign(self, func_name: str, *args: Any, observed: Any = None) -> SignatureResult:
        """Call ``func_name`` with ``args`` and optionally compare to ``observed``."""
        self.load()
        try:
            value = self.engine.call(func_name, *args)
            matches = observed is not None and value == observed
            return SignatureResult(func_name, value, matches=matches, observed=observed)
        except Exception as exc:  # noqa: BLE001
            return SignatureResult(func_name, None, error=str(exc))

    def crack(self, *args: Any, observed: Any = None) -> list[SignatureResult]:
        """Try every candidate function; return results, matches first."""
        results = [self.try_sign(name, *args, observed=observed) for name in self.candidates]
        results.sort(key=lambda r: (not r.matches, r.error is not None))
        return results


def beautify(js: str) -> str:
    """Reindent minified JS for human analysis (requires ``jsbeautifier``)."""
    try:
        import jsbeautifier

        return jsbeautifier.beautify(js)
    except Exception as exc:  # noqa: BLE001
        logger.debug("jsbeautifier unavailable: %s", exc)
        return js
