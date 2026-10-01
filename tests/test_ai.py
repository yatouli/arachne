"""AI 功能测试：用本地 mock LLM 服务器验证零依赖 httpx 客户端。"""

from __future__ import annotations

import http.server
import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _MockLLM(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content = json.dumps({"choices": [{"message": {"content": '{"title": "Hello", "author": "Jane"}'}}]})
        b = content.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *args):
        pass


def _serve():
    server = http.server.HTTPServer(("127.0.0.1", 0), _MockLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def test_llm_client_and_extract():
    server, base = _serve()
    try:
        from arachne.ai import extract_fields
        from arachne.ai.llm import LLMClient
        from arachne.page import Page

        client = LLMClient(base_url=base, model="test-model")
        out = client.complete("hi")
        assert "Hello" in out

        page = Page("http://x/", content="<html><body><h1>Hello</h1></body></html>")
        fields = extract_fields(page, {"title": "标题", "author": "作者"}, client=client)
        assert fields["title"] == "Hello"
        assert fields["author"] == "Jane"
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
