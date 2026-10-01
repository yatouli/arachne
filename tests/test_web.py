"""Web dashboard tests (in-process via Flask test client)."""

from __future__ import annotations

import http.server
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HTML = """<html><head><title>Shop</title></head><body>
<div class="product"><h3 class="title">Widget</h3><span class="price">$9.99</span></div>
<div class="product"><h3 class="title">Gadget</h3><span class="price">$19.99</span></div>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        b = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


def _make_app():
    from arachne.web.server import create_app

    return create_app(plugin_dirs=[])


def test_index_and_status():
    app = _make_app()
    client = app.test_client()

    resp = client.get("/")
    assert resp.status_code == 200
    assert "爬虫控制台" in resp.get_data(as_text=True)

    status = client.get("/api/status").get_json()
    assert status["version"]
    assert set(status["backends"]) == {"curl_cffi", "playwright", "mini_racer", "httpx"}


def test_js_endpoint():
    client = _make_app().test_client()
    r = client.post("/api/js", json={"code": "6 * 7"}).get_json()
    assert r["ok"] and r["result"] == 42

    # statement execution
    r2 = client.post("/api/js", json={"code": "function f(x){ return x + 1; } f(41)"}).get_json()
    assert r2["ok"] and r2["result"] == 42


def test_scrape_endpoint():
    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/"
    try:
        client = _make_app().test_client()
        r = client.post("/api/scrape", json={
            "url": base, "fetcher": "http", "use_plugins": False,
            "fields": [{"name": "title", "selector": "h3.title::text"}],
        }).get_json()
        assert r["ok"], r.get("error")
        assert r["status"] == 200
        assert r["title"] == "Shop"
        # ::text now joins all matches (both products)
        assert r["fields"]["title"] == "Widget\nGadget"
        assert not r["blocked"]["blocked"]
    finally:
        server.shutdown()


def test_create_plugin():
    import pathlib

    app = _make_app()
    client = app.test_client()
    r = client.post("/api/plugins", json={
        "name": "web_test_plugin",
        "mode": "schema",
        "domains": "example.org",
        "container": ".product",
        "fields": [{"name": "title", "selector": "h3::text"}],
    }).get_json()
    assert r["ok"], r.get("error")
    assert r["plugin"]["name"] == "web_test_plugin"
    assert "example.org" in r["plugin"]["domains"]
    # cleanup
    path = pathlib.Path(os.path.expanduser("~/.arachne/plugins/web_test_plugin.py"))
    if path.exists():
        path.unlink()


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
