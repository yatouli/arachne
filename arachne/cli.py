"""Command-line interface: ``arachne fetch|extract|plugins|js|version``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="arachne", description="Arachne — adaptive AI scraping framework")
    parser.add_argument("--version", action="version", version=f"arachne {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("url")
        p.add_argument("--stealth", action="store_true", help="use stealth browser")
        p.add_argument("--dynamic", action="store_true", help="use dynamic browser")
        p.add_argument("--impersonate", default=None, help="TLS fingerprint target (e.g. chrome124)")
        p.add_argument("--proxy", action="append", default=None, help="proxy URL (repeatable)")
        p.add_argument("--headless", action="store_true", default=True)

    f = sub.add_parser("fetch", help="fetch a URL and print its Markdown")
    common(f)
    f.add_argument("-o", "--output", default=None, help="write raw HTML to file")

    e = sub.add_parser("extract", help="fetch a URL and extract fields by CSS selector")
    common(e)
    e.add_argument("--field", action="append", default=[], metavar="NAME=SELECTOR",
                   help="field to extract (repeatable), e.g. title=h1::text")

    p = sub.add_parser("plugins", help="list registered site plugins")
    p.add_argument("--dir", action="append", default=[], help="extra plugin directory to load")

    j = sub.add_parser("js", help="evaluate a JS expression in the embedded engine")
    j.add_argument("code", help="JS expression")

    u = sub.add_parser("ui", help="start the interactive web dashboard")
    u.add_argument("--host", default="127.0.0.1", help="bind host (default 127.0.0.1)")
    u.add_argument("--port", type=int, default=8000, help="port (default 8000)")
    u.add_argument("--no-browser", action="store_true", help="do not auto-open the browser")
    u.add_argument("--plugins-dir", action="append", default=[], help="extra plugin directory (repeatable)")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.verbose:
        from .log import set_level
        import logging

        set_level(logging.DEBUG)

    from .config import Settings
    from .plugins.registry import load_all

    if args.command == "plugins":
        from .plugins.registry import default_registry

        load_all(default_registry, directories=args.dir)
        plugins = default_registry.all()
        if not plugins:
            print("No plugins registered.")
            return 0
        for plugin in plugins:
            print(f"{plugin.name:24s} domains={plugin.domains} {plugin.description}")
        return 0

    if args.command == "js":
        from .js_reverse.engine import JsEngine

        engine = JsEngine()
        print(engine.eval(args.code))
        return 0

    if args.command == "ui":
        from .web.server import run_server

        run_server(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            plugin_dirs=args.plugins_dir or None,
        )
        return 0

    # fetch / extract share the fetch path
    settings = Settings()
    if args.impersonate:
        settings = settings.merge(impersonate=args.impersonate)
    if args.proxy:
        settings = settings.merge(proxies=args.proxy, proxy_rotation="cyclic")

    from .engine import Arachne

    arachne = Arachne(settings)
    try:
        fetcher = "stealth" if args.stealth else ("dynamic" if args.dynamic else "http")
        page = arachne.fetch(args.url, fetcher=fetcher)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.command == "fetch":
        if args.output:
            with open(args.output, "w", encoding="utf-8") as fh:
                fh.write(page.text)
            print(f"saved {len(page.content)} bytes to {args.output}")
        else:
            print(page.markdown())
        return 0

    if args.command == "extract":
        result = {}
        for spec in args.field:
            name, _, selector = spec.partition("=")
            if not selector:
                print(f"invalid --field {spec!r} (expected NAME=SELECTOR)", file=sys.stderr)
                return 1
            result[name] = page.css(selector).get()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
