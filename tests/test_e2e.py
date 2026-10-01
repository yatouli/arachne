"""End-to-end test against a local HTTP server (no external network needed).

Runs both directly (``python tests/test_e2e.py``) and under pytest.
"""

from __future__ import annotations

import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HTML = """<html><head><title>Shop</title></head><body>
<div class="product"><h3 class="title">Widget</h3><span class="price">$9.99</span><a href="/p/widget">x</a></div>
<div class="product"><h3 class="title">Gadget</h3><span class="price">$19.99</span><a href="/p/gadget">x</a></div>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def test_fetch_spider_and_plugin():
    server, base = _serve()
    try:
        from arachne import Fetcher, Spider

        # 1. Plain fetch
        page = Fetcher.fetch(base, impersonate="chrome124")
        assert page.status_code == 200
        assert page.css("title::text").get() == "Shop"

        # 2. Spider
        class ShopSpider(Spider):
            name = "shop"
            start_urls = [base]
            custom_settings = {"concurrency": 2}

            async def parse(self, response):
                for p in response.css(".product"):
                    yield {
                        "title": p.css("h3.title::text").get(),
                        "price": p.css(".price::text").get(),
                    }

        result = ShopSpider().run()
        assert result.stats.items == 2
        assert result.items[0]["title"] == "Widget"

        # 3. Plugin engine auto-match
        from arachne.engine import Arachne
        from arachne.plugins import SitePlugin, plugin

        @plugin
        class LocalPlugin(SitePlugin):
            name = "local_shop"
            domains = ["127.0.0.1"]

            def parse(self, page):
                return page.css(".product").as_dicts(
                    title="h3.title::text", price=".price::text"
                )

        engine = Arachne()
        try:
            items = engine.scrape(base)
            assert isinstance(items, list) and items[0]["title"] == "Widget"
        finally:
            engine.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    import traceback

    total = sum(
        1 for n, fn in globals().items() if n.startswith("test_") and callable(fn)
    )
    passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
                passed += 1
            except Exception as exc:  # noqa: BLE001
                print(f"FAIL {name}: {exc}")
                traceback.print_exc()
    print(f"\n{passed}/{total} passed")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if passed == total else 1)
