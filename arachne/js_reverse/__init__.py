"""JS reverse-engineering (js逆向) package."""

from .engine import JsEngine, extract_script_srcs, extract_scripts
from .signatures import (
    SignatureCracker,
    SignatureResult,
    beautify,
    detect_hash_algorithms,
    extract_function_names,
    guess_signature_functions,
)
from .xhr import discover_all_urls, discover_api_endpoints, find_embedded_state

__all__ = [
    "JsEngine",
    "extract_scripts",
    "extract_script_srcs",
    "discover_all_urls",
    "discover_api_endpoints",
    "find_embedded_state",
    "SignatureCracker",
    "SignatureResult",
    "beautify",
    "detect_hash_algorithms",
    "extract_function_names",
    "guess_signature_functions",
]
