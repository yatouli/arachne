"""Sitemap 功能测试（本地 mock 服务器，确定性验证）。"""

from __future__ import annotations

import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SITEMAP_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://127.0.0.1:{port}/page/1</loc></url>
  <url><loc>http://127.0.0.1:{port}/page/2</loc></url>
  <url><loc>http://127.0.0.1:{port}/page/3</loc></url>
</urlset>"""

PAGE_HTML = (
    "<html><head><title>Page {n}</title></head><body>"
    "<article><h1>Article {n}</h1>"
    "<p>Some meaningful content for article number {n}, with enough length "
    "to be scored as the main text body of the page here.</p></article></body></html>"
)


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"<html><body>other</body></html>"
        ctype = "text/html"
        if self.path == "/robots.txt":
            body = f"Sitemap: http://127.0.0.1:{self.server.server_address[1]}/sitemap.xml\n".encode()
            ctype = "text/plain"
        elif self.path == "/sitemap.xml":
            body = SITEMAP_TEMPLATE.format(port=self.server.server_address[1]).encode()
            ctype = "application/xml"
        elif self.path.startswith("/page/"):
            body = PAGE_HTML.format(n=self.path.rsplit("/", 1)[1]).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def _serve():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_sitemap_discovery_and_crawl():
    server, base = _serve()
    try:
        from arachne.fetchers.http import Fetcher
        from arachne.spider import SitemapSpider, discover_sitemap_urls, resolve_sitemap_urls

        fetcher = Fetcher()
        sitemaps = discover_sitemap_urls(base + "/", fetcher)
        assert sitemaps, "should discover sitemap via robots.txt"

        urls = resolve_sitemap_urls(sitemaps, fetcher, max_urls=10)
        assert len(urls) == 3, f"expected 3 urls, got {len(urls)}"

        spider = SitemapSpider(sitemap_urls=sitemaps, fields={"title": "title::text"}, concurrency=2)
        result = spider.run()
        assert len(result.items) == 3
        assert result.items[0]["title"].startswith("Page ")
    finally:
        server.shutdown()


if __name__ == "__main__":
    import traceback

    total = sum(1 for n, fn in globals().items() if n.startswith("test_") and callable(fn))
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
