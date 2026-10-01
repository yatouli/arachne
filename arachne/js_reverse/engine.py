"""Embedded JavaScript execution engine with pluggable backends.

Backends, tried in order for ``engine="auto"``:

1. ``mini_racer`` — in-process V8 (persistent context, JSON round-trip). Preferred.
2. ``node`` — a one-shot Node subprocess per call (no persistent context).
3. ``quickjs`` — the pure-Python ``quickjs`` package.

Use it to run a site's obfuscated JS, reproduce its request signature, decrypt
payloads, or brute-force a hash. For signature workflows see
:mod:`arachne.js_reverse.signatures`.
"""

from __future__ import annotations

import atexit
import json
import re
import shutil
import subprocess
from typing import Any, Optional

from ..exceptions import JsEngineUnavailableError, JsError
from ..log import get_logger

logger = get_logger("js")

#: Keep track of live engines so the V8 isolate can be freed at exit (some
#: backends leave a non-daemon background thread otherwise).
_LIVE_ENGINES: set["JsEngine"] = set()


def _close_all_engines() -> None:
    for engine in list(_LIVE_ENGINES):
        try:
            engine.close()
        except Exception:  # noqa: BLE001
            pass


atexit.register(_close_all_engines)


class _MiniRacerBackend:
    def __init__(self, racer):
        self._racer = racer

    def eval(self, js: str) -> Any:
        try:
            raw = self._racer.eval(
                "JSON.stringify((function(){ return (" + js + "); })())"
            )
            return None if raw is None else json.loads(raw)
        except Exception:
            # Fall back to a direct eval (may return non-JSON types).
            return self._racer.eval(js)

    def define(self, name: str, value: Any) -> None:
        self._racer.eval(f"globalThis[{json.dumps(name)}] = {json.dumps(value)};")

    def run(self, code: str) -> Any:
        # Statements execute at global scope, so `function f(){}` becomes callable.
        return self._racer.eval(code)

    def close(self) -> None:
        # Free the V8 isolate so its background thread stops (prevents the
        # interpreter from hanging at exit on some platforms).
        try:
            self._racer.close()
        except Exception:  # noqa: BLE001
            pass


class _NodeBackend:
    def __init__(self, node_path: str, timeout: float = 30.0):
        self.node_path = node_path
        self.timeout = timeout
        self._defs: dict[str, Any] = {}

    def define(self, name: str, value: Any) -> None:
        self._defs[name] = value

    def _preamble(self) -> str:
        return "\n".join(
            f"globalThis.{json.dumps(k)} = {json.dumps(v)};" for k, v in self._defs.items()
        )

    def eval(self, js: str) -> Any:
        marker = "__ARACHNE_RESULT__"
        wrapper = (
            self._preamble()
            + f"\ntry {{ console.log('{marker}' + JSON.stringify((function(){{ return ({js}); }})())); }}"
            + " catch (e) { console.error(e && e.stack ? e.stack : String(e)); process.exit(1); }"
        )
        try:
            proc = subprocess.run(
                [self.node_path, "-e", wrapper],
                capture_output=True, text=True, timeout=self.timeout,
            )
        except FileNotFoundError as exc:
            raise JsEngineUnavailableError(f"node not found at {self.node_path!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise JsError("node eval timed out") from exc
        if proc.returncode != 0:
            raise JsError(proc.stderr.strip() or "node eval failed")
        for line in proc.stdout.splitlines():
            if line.startswith(marker):
                payload = line[len(marker):]
                return json.loads(payload) if payload not in ("undefined", "") else None
        return None

    def close(self) -> None:
        pass


class _QuickJsBackend:
    def __init__(self, quickjs):
        self._ctx = quickjs.Context()

    def eval(self, js: str) -> Any:
        try:
            return json.loads(self._ctx.eval(f"JSON.stringify((function(){{ return ({js}); }})())"))
        except Exception:
            return self._ctx.eval(js)

    def define(self, name: str, value: Any) -> None:
        self._ctx.eval(f"globalThis.{name} = {json.dumps(value)};")

    def run(self, code: str) -> Any:
        return self._ctx.eval(code)

    def close(self) -> None:
        pass


class JsEngine:
    """A convenience wrapper over the best available JS backend."""

    def __init__(self, engine: str = "auto", node_path: str = "node", timeout: float = 30.0):
        self.engine = engine
        self.node_path = node_path
        self.timeout = timeout
        self._backend: Any = None
        self._select()
        _LIVE_ENGINES.add(self)

    def _select(self) -> None:
        order = ["mini_racer", "node", "quickjs"]
        if self.engine != "auto":
            order = [self.engine] + [e for e in order if e != self.engine]
        for name in order:
            backend = self._try_backend(name)
            if backend is not None:
                self.engine = name
                self._backend = backend
                logger.debug("JsEngine using backend: %s", name)
                return
        raise JsEngineUnavailableError(
            "no JS engine available; install `pip install py_mini_racer` or ensure Node is on PATH"
        )

    def _try_backend(self, name: str) -> Any:
        if name == "mini_racer":
            try:
                from py_mini_racer import MiniRacer

                return _MiniRacerBackend(MiniRacer())
            except Exception:  # noqa: BLE001
                return None
        if name == "node":
            if shutil.which(self.node_path):
                return _NodeBackend(self.node_path, self.timeout)
            return None
        if name == "quickjs":
            try:
                import quickjs  # type: ignore

                return _QuickJsBackend(quickjs)
            except Exception:  # noqa: BLE001
                return None
        return None

    # ---- public API -----------------------------------------------------
    def eval(self, js: str) -> Any:
        """Evaluate a JS expression and return a Python value."""
        return self._backend.eval(js)

    def run(self, code: str) -> Any:
        """Execute statements (mini_racer/quickjs keep the context)."""
        runner = getattr(self._backend, "run", None)
        if runner is not None:
            return runner(code)
        # Node backend is stateless; wrap statements as an IIFE expression.
        code = code.rstrip().rstrip(";")
        return self._backend.eval(f"(()=>{{ {code} }})()")

    def define(self, name: str, value: Any) -> "JsEngine":
        """Inject a JSON-serializable value into the JS global scope."""
        self._backend.define(name, value)
        return self

    def call(self, func_expr: str, *args: Any) -> Any:
        """Call a JS function (name or expression) with JSON arguments."""
        return self._backend.eval(f"({func_expr}).apply(null, {json.dumps(list(args))})")

    def close(self) -> None:
        try:
            self._backend.close()
        finally:
            _LIVE_ENGINES.discard(self)

    def __enter__(self) -> "JsEngine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def extract_scripts(html: str) -> list[str]:
    """Return the *inline* ``<script>`` bodies of an HTML document."""
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.I | re.S)


def extract_script_srcs(html: str) -> list[str]:
    """Return external script ``src`` URLs."""
    return re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", html, re.I)
