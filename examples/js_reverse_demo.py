"""JS reverse-engineering demo.

Shows the three pieces of the 逆向 workflow:
1. run JS in the embedded V8 engine,
2. reproduce a "signature" function a site might use,
3. discover API endpoints / embedded JSON from a page.
"""

from arachne.js_reverse import (
    SignatureCracker,
    detect_hash_algorithms,
    discover_api_endpoints,
    find_embedded_state,
)
from arachne.js_reverse.engine import JsEngine

# 1 + 2. Reproduce a signature.
with JsEngine() as engine:  # auto-selects py_mini_racer (V8) here
    print("engine backend:", engine.engine)

    site_js = """
    var SECRET = "s3cr3t-key";
    function md5(s){ return "md5(" + s + ")"; }              // stub
    function makeSign(timestamp, payload) {
        // A realistic site: sign = md5(timestamp + payload + SECRET)
        return md5(timestamp + payload + SECRET);
    }
    """

    cracker = SignatureCracker(js=site_js, engine=engine)
    cracker.find_candidates()
    print("candidate signers:", cracker.candidates)
    print("hash algorithms detected:", detect_hash_algorithms(site_js))

    observed = "md5(1699999999hello-worlds3cr3t-key)"
    results = cracker.crack("1699999999", "hello-world", observed=observed)
    for r in results:
        print(f"  {r.function_name}: {r.value!r}  match={r.matches}  err={r.error}")

# 3. Endpoint discovery from an HTML snippet.
html = """
<html><body>
<script>window.__INITIAL_STATE__ = {"products": [{"id": 1, "name": "Widget"}]};</script>
<script>fetch("/api/v2/products?page=1").then(r => r.json())</script>
<a href="/api/v1/cart.json">cart</a>
</body></html>
"""
print("\napi endpoints:", discover_api_endpoints(html, "https://shop.example"))
print("embedded state:", find_embedded_state(html))
