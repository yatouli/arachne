"""Core tests. Runnable via ``pytest`` or directly: ``python tests/test_core.py``."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

HTML = """
<html><head><title>Test Shop</title></head><body>
  <h1 id="title">Our Products</h1>
  <div class="product" data-test="product">
    <h3 class="title">Widget</h3>
    <span class="price">$9.99</span>
    <a href="/p/widget">Details</a>
  </div>
  <div class="product" data-test="product">
    <h3 class="title">Gadget</h3>
    <span class="price">$19.99</span>
    <a href="/p/gadget">Details</a>
  </div>
  <script>window.__INITIAL_STATE__ = {"count": 2};</script>
  <script>fetch("/api/v2/products").then(r => r.json())</script>
</body></html>
"""


def _page():
    from arachne.page import Page

    return Page("https://shop.example/", content=HTML)


def test_selector():
    from arachne.parsing import from_text

    sel = from_text(HTML)
    assert sel.css("title::text").get() == "Test Shop"
    assert sel.css("h3.title::text").getall() == ["Widget", "Gadget"]
    assert sel.xpath("//h3[@class='title']/text()").get() == "Widget"
    assert sel.re(r"Widget|Gadget") == ["Widget", "Gadget"]
    assert sel.css(".product").first.attrib("data-test") == "product"
    assert len(sel.css(".product")) == 2


def test_schema():
    from arachne.parsing import Field, Schema

    schema = Schema(
        container=".product",
        fields=[
            Field(name="title", selector="h3.title::text"),
            Field(name="price", selector=".price::text", type=float),
            Field(name="url", selector="a::attr(href)"),
        ],
    )
    records = schema.extract(_page())
    assert records[0]["title"] == "Widget"
    assert records[0]["price"] == 9.99
    assert records[1]["url"] == "/p/gadget"


def test_adaptive_relocate():
    from arachne.parsing import ElementFingerprint, relocate

    page = _page()
    h1 = page.css("h1").first
    fp = ElementFingerprint.from_element(h1)
    # A modified page where the title moved.
    modified = HTML.replace('<h1 id="title">Our Products</h1>',
                            '<div><section><h1 id="title">Our Products</h1></section></div>')
    page2 = _page()
    page2._content = modified.encode()
    page2._text = None
    page2._selector = None
    matches = relocate(page2.selector, fp, threshold=0.4)
    assert matches.first is not None
    assert matches.first.text() == "Our Products"


def test_headers_and_fingerprint():
    from arachne.antidetect import build_headers, fingerprint_for

    fp = fingerprint_for("chrome124")
    assert "Chrome/124" in fp["user_agent"]
    headers = build_headers("chrome124")
    assert headers["user-agent"] == fp["user_agent"]
    assert headers["sec-ch-ua-platform"] == '"Windows"'


def test_proxy_rotator():
    from arachne.antidetect import ProxyRotator, parse_proxy

    r = ProxyRotator(["http://a:1", "http://b:2"], strategy="cyclic")
    assert [r.next(), r.next(), r.next()] == ["http://a:1", "http://b:2", "http://a:1"]
    info = parse_proxy("http://user:pass@host:8080")
    assert info["host"] == "host" and info["username"] == "user" and info["port"] == 8080


def test_challenge_detection():
    from arachne.antidetect import detect_block
    from arachne.page import Page

    blocked = Page(
        "https://x", status_code=403,
        content=b"<html><title>Just a moment...</title><div class='cf-turnstile'></div></html>",
        headers={"cf-mitigated": "challenge"},
    )
    info = detect_block(blocked)
    assert info.blocked and info.kind in {"cloudflare", "challenge"}

    ok = Page("https://x", status_code=200, content=HTML)
    assert not detect_block(ok).blocked


def test_js_engine():
    from arachne.js_reverse.engine import JsEngine

    engine = JsEngine()
    assert engine.eval("1 + 2") == 3
    assert engine.call("(function(a, b){ return a * b; })", 6, 7) == 42
    engine.define("API_KEY", "abc")
    assert engine.eval("API_KEY") == "abc"


def test_signature_cracker():
    from arachne.js_reverse import SignatureCracker
    from arachne.js_reverse.engine import JsEngine

    js = "function sign(t, p){ return 'x' + t + '-' + p; }"
    cracker = SignatureCracker(js=js, engine=JsEngine())
    cracker.find_candidates()
    result = cracker.try_sign("sign", "1", "hello", observed="x1-hello")
    assert result.matches and result.value == "x1-hello"


def test_plugins():
    from arachne.plugins import PluginRegistry, SitePlugin, plugin

    class Demo(SitePlugin):
        name = "demo"
        domains = ["example.org"]

        def parse(self, page):
            return {"title": page.css("title::text").get()}

    reg = PluginRegistry()
    reg.register(Demo)
    assert reg.match("https://sub.example.org/x") is Demo
    assert reg.match("https://other.com") is None


def test_readable_and_autolist():
    article_html = """
    <html><head><title>Test Article</title>
      <meta property="og:image" content="https://x/img.jpg"></head>
    <body>
      <nav><a href="/">Home</a> <a href="/about">About</a></nav>
      <script>var junk = "x".repeat(5000);</script>
      <article>
        <h1>My Great Post</h1>
        <p>This is the first paragraph of real content, with enough length to score well.</p>
        <p>This is the second paragraph, also quite substantial and meaningful text here.</p>
        <p>Third paragraph continues the story with more useful information for readers.</p>
      </article>
      <footer>Copyright 2024</footer>
    </body></html>
    """
    page = _page()
    page._content = article_html.encode()
    page._text = None
    page._selector = None

    rd = page.readable()
    assert rd["title"] == "My Great Post"
    assert "first paragraph" in rd["content"]
    assert "var junk" not in rd["content"]  # script excluded
    assert rd["image"] == "https://x/img.jpg"

    # autolist on a list page
    list_html = """
    <html><body><ul class="cards">
      <li class="card"><a href="/item/1"><h3>Item One</h3></a><img src="/i/1.jpg"></li>
      <li class="card"><a href="/item/2"><h3>Item Two</h3></a><img src="/i/2.jpg"></li>
      <li class="card"><a href="/item/3"><h3>Item Three</h3></a><img src="/i/3.jpg"></li>
    </ul></body></html>
    """
    page2 = _page()
    page2._content = list_html.encode()
    page2._text = None
    page2._selector = None
    items = page2.list_items(min_items=3)
    assert len(items) == 3
    assert items[0]["url"].endswith("/item/1")
    assert items[0]["title"] == "Item One"
    assert items[0]["image"].endswith("/i/1.jpg")


def test_page_markdown_and_state():
    from arachne.js_reverse import discover_api_endpoints, find_embedded_state

    page = _page()
    md = page.markdown()
    assert "# Our Products" in md
    assert "Widget" in md
    endpoints = discover_api_endpoints(page.text, page.url)
    assert any("/api/v2/products" in u for u in endpoints)
    state = find_embedded_state(page)
    assert state.get("__INITIAL_STATE__") == {"count": 2}


if __name__ == "__main__":
    total = sum(
        1 for name, fn in globals().items() if name.startswith("test_") and callable(fn)
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
                import traceback

                traceback.print_exc()
    print(f"\n{passed}/{total} passed")
    # py_mini_racer's embedded V8 may leave non-daemon threads running; flush
    # then exit explicitly so the process neither hangs nor drops buffered output.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0 if passed == total else 1)
