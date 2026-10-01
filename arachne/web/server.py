"""Flask backend for the Arachne web dashboard.

Endpoints:
  * ``GET  /``                     the single-page dashboard
  * ``GET  /api/status``           version + available backends + plugins
  * ``POST /api/scrape``           run a scrape (fetcher, anti-bot options, fields)
  * ``POST /api/js``               evaluate JS in the embedded engine
  * ``GET  /api/plugins``          list registered plugins
  * ``POST /api/plugins``          create a plugin (schema form or raw code)
"""

from __future__ import annotations

import os
import pathlib
import re
import threading
import time
import traceback
import webbrowser
from typing import Any, Optional

from flask import Flask, jsonify, render_template, request

import arachne
from ..config import Settings
from ..log import get_logger
from ..plugins.base import SitePlugin, plugin as plugin_decorator
from ..plugins.registry import PluginRegistry, load_all

logger = get_logger("web")

# ---- plugin directory resolution ---------------------------------------
_PKG_DIR = pathlib.Path(arachne.__file__).parent
_PROJECT_DIR = _PKG_DIR.parent
_BUNDLED_PLUGINS = _PROJECT_DIR / "plugins"
_USER_PLUGINS = pathlib.Path(os.path.expanduser("~/.arachne/plugins"))


def _default_plugin_dirs() -> list[str]:
    dirs: list[str] = []
    for d in (_BUNDLED_PLUGINS, _USER_PLUGINS):
        if d.is_dir():
            dirs.append(str(d))
    return dirs


def _available_backends() -> dict[str, bool]:
    checks = {
        "curl_cffi": lambda: _import_ok("curl_cffi"),
        "playwright": lambda: _import_ok("playwright"),
        "mini_racer": lambda: _import_ok("py_mini_racer"),
        "httpx": lambda: _import_ok("httpx"),
    }
    return {name: fn() for name, fn in checks.items()}


def _import_ok(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:  # noqa: BLE001
        return False


class _State:
    """Shared mutable state: plugin registry + extra dirs."""

    def __init__(self, plugin_dirs: Optional[list[str]] = None):
        self.plugin_dirs = list(plugin_dirs or _default_plugin_dirs())
        self.registry = PluginRegistry()
        self._ensure_user_dir()
        self.reload()

    def _ensure_user_dir(self) -> None:
        try:
            _USER_PLUGINS.mkdir(parents=True, exist_ok=True)
            if str(_USER_PLUGINS) not in self.plugin_dirs:
                self.plugin_dirs.append(str(_USER_PLUGINS))
        except Exception:  # noqa: BLE001
            pass

    def reload(self) -> None:
        # Rebuild a fresh registry each time so deleted files drop out.
        self.registry = PluginRegistry()
        load_all(self.registry, directories=self.plugin_dirs)


def create_app(plugin_dirs: Optional[list[str]] = None) -> Flask:
    app = Flask(__name__)
    state = _State(plugin_dirs)

    # ---- static pages ---------------------------------------------------
    @app.get("/")
    def index():
        return render_template("index.html", version=arachne.__version__)

    # ---- status ---------------------------------------------------------
    @app.get("/api/status")
    def status():
        from ..antidetect.fingerprints import supported_impersonates

        return jsonify({
            "version": arachne.__version__,
            "backends": _available_backends(),
            "impersonates": supported_impersonates(),
            "plugin_dirs": state.plugin_dirs,
            "plugins": _plugin_list(state.registry),
        })

    @app.get("/api/plugins")
    def plugins():
        return jsonify(_plugin_list(state.registry))

    # ---- scrape ---------------------------------------------------------
    @app.post("/api/scrape")
    def scrape():
        params = request.get_json(silent=True) or {}
        started = time.perf_counter()
        try:
            result = _run_scrape(params, state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("scrape failed")
            return jsonify({
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "url": (params.get("url") or "").strip(),
                "duration": round(time.perf_counter() - started, 3),
            }), 200
        result["duration"] = round(time.perf_counter() - started, 3)
        return jsonify(result)

    # ---- js -------------------------------------------------------------
    @app.post("/api/js")
    def js():
        data = request.get_json(silent=True) or {}
        code = data.get("code", "")
        try:
            from ..js_reverse.engine import JsEngine

            with JsEngine() as engine:
                value = engine.eval(code) if _is_expression(code) else engine.run(code)
            return jsonify({"ok": True, "result": _jsonsafe(value), "backend": engine.engine})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})

    # ---- crawl (batch spider) -------------------------------------------
    @app.post("/api/crawl")
    def crawl():
        data = request.get_json(silent=True) or {}
        try:
            result = _run_crawl(data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("crawl failed")
            return jsonify({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        return jsonify(result)

    # ---- sitemap --------------------------------------------------------
    @app.post("/api/sitemap")
    def sitemap():
        data = request.get_json(silent=True) or {}
        try:
            result = _run_sitemap(data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sitemap failed")
            return jsonify({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        return jsonify(result)

    # ---- ai extract -----------------------------------------------------
    @app.post("/api/ai_extract")
    def ai_extract():
        data = request.get_json(silent=True) or {}
        try:
            result = _run_ai_extract(data)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ai extract failed")
            return jsonify({"ok": False, "error": str(exc), "traceback": traceback.format_exc()})
        return jsonify(result)

    # ---- plugin create --------------------------------------------------
    @app.post("/api/plugins")
    def create_plugin():
        data = request.get_json(silent=True) or {}
        try:
            info = _create_plugin(data, state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("plugin create failed")
            return jsonify({"ok": False, "error": str(exc), "traceback": traceback.format_exc()}), 200
        return jsonify({"ok": True, "plugin": info})

    return app


# --------------------------------------------------------------------------
# Scrape implementation
# --------------------------------------------------------------------------
def _run_scrape(params: dict[str, Any], state: _State) -> dict[str, Any]:
    url = (params.get("url") or "").strip()
    if not url:
        raise ValueError("请填写要抓取的 URL")
    if not re.match(r"^https?://", url):
        url = "https://" + url

    settings = _build_settings(params)
    fetcher = params.get("fetcher") or "http"
    use_plugins = bool(params.get("use_plugins", True))
    capture_xhr = params.get("capture_xhr") or None

    result: dict[str, Any] = {
        "ok": True, "url": url, "fetcher": fetcher,
        "matched_plugin": None, "items": None, "fields": None,
        "markdown": "", "html": "", "xhr": [], "blocked": None,
        "status": None, "title": None, "readable": None, "list_items": None,
        "images": None, "error": None,
    }

    # Fresh engine per request so proxies/throttle are isolated.
    from ..engine import Arachne

    engine = Arachne(settings, registry=PluginRegistry(), plugin_dirs=state.plugin_dirs)
    try:
        plugin_cls = engine.match_plugin(url) if use_plugins else None
        fetcher_obj = engine._fetcher_for(fetcher)

        fetch_kwargs: dict[str, Any] = {}
        if fetcher in ("dynamic", "stealth") and capture_xhr:
            fetch_kwargs["capture_xhr"] = capture_xhr
        if fetcher == "stealth":
            fetch_kwargs["challenge_wait"] = float(params.get("challenge_wait", 15) or 15)

        page = fetcher_obj._fetch(url, **fetch_kwargs)

        result["status"] = page.status_code
        result["title"] = page.css("title::text").get()
        result["html"] = page.text[:200_000]
        result["markdown"] = page.markdown()
        result["xhr"] = [_xhr_to_dict(x) for x in page.captured_xhr]
        result["blocked"] = _block_to_dict(page)

        if params.get("readable"):
            result["readable"] = page.readable()
        if params.get("auto_list"):
            result["list_items"] = _jsonsafe(page.list_items(min_items=3))
        if params.get("download_images"):
            result["images"] = _download_images(page, params.get("download_dir") or "downloads")

        if plugin_cls is not None:
            result["matched_plugin"] = plugin_cls.name
            plugin = plugin_cls()
            items = plugin.parse(page)
            result["items"] = _jsonsafe(_normalize_items(items))

        fields = params.get("fields") or []
        if fields:
            extracted: dict[str, Any] = {}
            for field in fields:
                name = (field.get("name") or "").strip()
                selector = (field.get("selector") or "").strip()
                if name and selector:
                    extracted[name] = _extract_field(page, selector)
            result["fields"] = extracted
    finally:
        engine.close()
    return result


def _build_settings(params: dict[str, Any]) -> Settings:
    settings = Settings()
    if params.get("impersonate"):
        settings = settings.merge(impersonate=params["impersonate"])
    proxy = (params.get("proxy") or "").strip()
    if proxy:
        settings = settings.merge(proxies=[proxy], proxy_rotation="cyclic")
    if "headless" in params:
        settings = settings.merge(headless=bool(params["headless"]))
    return settings


def _run_crawl(data: dict[str, Any]) -> dict[str, Any]:
    start_url = (data.get("start_url") or "").strip()
    if not start_url:
        raise ValueError("请填写起始列表页 URL")
    if not re.match(r"^https?://", start_url):
        start_url = "https://" + start_url

    link_regex = (data.get("link_regex") or "").strip() or None
    fields: dict[str, str] = {}
    for field in data.get("fields") or []:
        name = (field.get("name") or "").strip()
        selector = (field.get("selector") or "").strip()
        if name and selector:
            fields[name] = selector
    pages = max(1, int(data.get("pages") or 1))
    image_field = (data.get("image_field") or "").strip() or None
    download_dir = (data.get("download_dir") or "downloads").strip() or "downloads"
    concurrency = max(1, min(16, int(data.get("concurrency") or 4)))
    auto_links = bool(data.get("auto_links", True)) and link_regex is None

    from ..spider import ConfigSpider

    settings = _build_settings(data)
    spider = ConfigSpider(
        start_url=start_url,
        link_regex=link_regex,
        fields=fields,
        pages=pages,
        image_field=image_field,
        download_dir=download_dir,
        auto_links=auto_links,
        settings=settings,
        concurrency=concurrency,
    )
    result = spider.run()
    return {
        "ok": True,
        "items": result.items,
        "count": len(result.items),
        "downloaded": spider.downloaded,
        "download_dir": download_dir,
        "stats": result.stats.as_dict(),
    }


def _run_sitemap(data: dict[str, Any]) -> dict[str, Any]:
    url = (data.get("url") or "").strip()
    if not url:
        raise ValueError("请填写域名或网址")
    if not re.match(r"^https?://", url):
        url = "https://" + url

    limit = max(1, min(500, int(data.get("limit") or 50)))
    concurrency = max(1, min(16, int(data.get("concurrency") or 4)))
    image_field = (data.get("image_field") or "").strip() or None
    download_dir = (data.get("download_dir") or "downloads").strip() or "downloads"
    fields: dict[str, str] = {}
    for field in data.get("fields") or []:
        name = (field.get("name") or "").strip()
        selector = (field.get("selector") or "").strip()
        if name and selector:
            fields[name] = selector

    from ..fetchers.http import Fetcher
    from ..spider.sitemap import SitemapSpider, discover_sitemap_urls, resolve_sitemap_urls

    settings = _build_settings(data)
    fetcher = Fetcher(settings)
    sitemap_urls = discover_sitemap_urls(url, fetcher)
    if not sitemap_urls:
        return {"ok": False, "error": "未发现 sitemap.xml（已尝试 robots.txt 与常见路径）"}

    all_urls = resolve_sitemap_urls(sitemap_urls, fetcher, max_urls=3000)
    if not all_urls:
        return {"ok": False, "error": "sitemap 解析后没有页面 URL"}

    spider = SitemapSpider(
        urls=all_urls,
        fields=fields,
        image_field=image_field,
        download_dir=download_dir,
        limit=limit,
        settings=settings,
        concurrency=concurrency,
    )
    result = spider.run()
    return {
        "ok": True,
        "sitemap_urls": sitemap_urls,
        "total_in_sitemap": len(all_urls),
        "items": result.items,
        "count": len(result.items),
        "downloaded": spider.downloaded,
        "download_dir": download_dir,
        "stats": result.stats.as_dict(),
    }


def _run_ai_extract(data: dict[str, Any]) -> dict[str, Any]:
    url = (data.get("url") or "").strip()
    field_spec = data.get("field_spec") or {}
    if not url:
        raise ValueError("请填写 URL")
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if not isinstance(field_spec, dict) or not field_spec:
        raise ValueError("请填写要提取的字段（名称 = 描述）")

    from ..ai import extract_fields
    from ..ai.llm import LLMClient
    from ..config import Settings
    from ..fetchers.http import Fetcher

    settings = Settings.from_env()
    if data.get("base_url"):
        settings = settings.merge(llm_base_url=data["base_url"])
    if data.get("api_key"):
        settings = settings.merge(llm_api_key=data["api_key"])
    if data.get("model"):
        settings = settings.merge(llm_model=data["model"])

    if not settings.llm_api_key and not settings.llm_base_url:
        raise ValueError(
            "未配置 LLM。请设置环境变量 ARACHNE_LLM_BASE_URL / ARACHNE_LLM_API_KEY，"
            "或在请求里传 base_url / api_key（支持 OpenAI 兼容接口，如 Ollama/vLLM）"
        )

    page = Fetcher(settings)._fetch(url)
    client = LLMClient.from_settings(settings)
    fields_result = extract_fields(page, field_spec, client=client)
    return {"ok": True, "fields": fields_result}


def _extract_field(page, selector: str) -> Any:
    """Extract a field value from a page given a CSS selector.

    * ``...::text``        -> all text matches joined by newlines
    * ``...::attr(name)``  -> all attribute values joined by newlines
    * element selector     -> the element's clean visible text (``//text()``)
    """
    if "::text" in selector:
        values = page.css(selector).getall()
        return "\n".join(values) if values else None
    if "::attr" in selector:
        values = page.css(selector).getall()
        return "\n".join(values) if values else None
    first = page.css(selector).first
    if first is None:
        return None
    return first.text()


_IMAGE_SELECTORS = [
    "img::attr(src)",
    "img::attr(data-src)",
    "img::attr(data-original)",
    'meta[property="og:image"]::attr(content)',
]


def _collect_image_urls(page) -> list[str]:
    from urllib.parse import urljoin

    urls: list[str] = []
    seen: set[str] = set()
    for selector in _IMAGE_SELECTORS:
        for value in page.css(selector).getall():
            value = (value or "").strip()
            if not value or value.startswith("data:"):
                continue
            absolute = urljoin(page.url, value)
            if absolute not in seen:
                seen.add(absolute)
                urls.append(absolute)
    return urls


def _filename_for(url: str, content_type: str) -> str:
    from urllib.parse import urlparse

    name = urlparse(url).path.rsplit("/", 1)[-1] or "image"
    if "." not in name:
        ext = {
            "image/jpeg": "jpg", "image/png": "png", "image/gif": "gif",
            "image/webp": "webp", "image/bmp": "bmp", "image/svg+xml": "svg",
        }.get(content_type, "img")
        name += f".{ext}"
    return re.sub(r"[^\w.\-]", "_", name)


def _download_images(page, download_dir: str, max_images: int = 200) -> dict[str, Any]:
    from ..fetchers.http import Fetcher

    urls = _collect_image_urls(page)[:max_images]
    os.makedirs(download_dir, exist_ok=True)
    fetcher = Fetcher()
    results: list[dict[str, Any]] = []
    try:
        for url in urls:
            try:
                img = fetcher._fetch(url, raise_on_block=False)
                if img.status_code != 200 or "image" not in (img.headers.get("content-type") or ""):
                    continue
                name = _filename_for(url, img.headers.get("content-type", ""))
                path = os.path.join(download_dir, name)
                with open(path, "wb") as fh:
                    fh.write(img.content)
                results.append({"url": url, "path": path, "size": len(img.content)})
            except Exception:  # noqa: BLE001
                continue
    finally:
        fetcher.close()
    return {"count": len(results), "dir": download_dir, "images": results}


def _normalize_items(items: Any) -> list[dict[str, Any]]:
    if items is None:
        return []
    if isinstance(items, dict):
        return [items]
    return [dict(i) if isinstance(i, dict) else {"value": i} for i in items]


def _xhr_to_dict(xhr) -> dict[str, Any]:
    return {
        "url": getattr(xhr, "url", ""),
        "method": getattr(xhr, "method", "GET"),
        "status": getattr(xhr, "status", None),
        "body": (getattr(xhr, "body", "") or "")[:20_000],
    }


def _block_to_dict(page) -> dict[str, Any]:
    from ..antidetect.challenge import detect_block

    info = detect_block(page)
    return {"blocked": info.blocked, "kind": info.kind, "reason": info.reason, "score": info.score}


# --------------------------------------------------------------------------
# JS helpers
# --------------------------------------------------------------------------
def _is_expression(code: str) -> bool:
    stripped = code.strip()
    # Simple heuristic: statements (function/var/const/let/if/for/return) -> run
    return not re.match(r"^(function|var|let|const|if|for|while|return|class)\b", stripped)


def _jsonsafe(value: Any) -> Any:
    import json

    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


# --------------------------------------------------------------------------
# Plugin helpers
# --------------------------------------------------------------------------
def _plugin_list(registry: PluginRegistry) -> list[dict[str, Any]]:
    out = []
    for cls in registry.all():
        out.append({
            "name": cls.name,
            "domains": list(cls.domains),
            "url_patterns": list(cls.url_patterns),
            "description": cls.description,
            "fetcher": cls.fetcher,
            "priority": cls.priority,
        })
    return out


def _create_plugin(data: dict[str, Any], state: _State) -> dict[str, Any]:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", (data.get("name") or "").strip())
    if not name:
        raise ValueError("插件需要一个名称")

    if data.get("mode") == "raw":
        code = data.get("code") or ""
        if not code.strip():
            raise ValueError("插件代码为空")
    else:
        domains = (data.get("domains") or "").strip()
        container = (data.get("container") or "").strip()
        fields = data.get("fields") or []
        fields = [f for f in fields if (f.get("name") or "").strip() and (f.get("selector") or "").strip()]
        if not domains:
            raise ValueError("至少填写一个域名")
        code = _generate_plugin_code(
            name=name,
            domains=domains,
            container=container,
            fields=fields,
            description=(data.get("description") or "").strip(),
        )

    # Syntax check.
    try:
        compile(code, f"{name}.py", "exec")
    except SyntaxError as exc:
        raise ValueError(f"代码语法错误: {exc}") from exc

    # Write and reload.
    _USER_PLUGINS.mkdir(parents=True, exist_ok=True)
    target = _USER_PLUGINS / f"{name}.py"
    target.write_text(code, encoding="utf-8")
    state.reload()

    cls = state.registry.get(name)
    if cls is None:
        raise ValueError(f"插件 {name!r} 写入成功但未能注册（检查代码里是否 @plugin 且类名正确）")
    return {
        "name": cls.name,
        "domains": list(cls.domains),
        "description": cls.description,
        "fetcher": cls.fetcher,
        "code": code,
    }


def _class_name(name: str) -> str:
    parts = [p.capitalize() for p in name.split("_") if p]
    return "".join(parts) + "Plugin"


def _generate_plugin_code(
    name: str, domains: str, container: str, fields: list[dict[str, Any]], description: str,
) -> str:
    domains_list = ", ".join(repr(d.strip()) for d in domains.split(",") if d.strip())
    field_lines = "\n            ".join(
        f"Field(name={f['name'].strip()!r}, selector={f['selector'].strip()!r})," for f in fields
    )
    container_literal = repr(container) if container else "None"
    return (
        "from arachne.parsing import Field, Schema\n"
        "from arachne.plugins import SitePlugin, plugin\n\n\n"
        "@plugin\n"
        f"class {_class_name(name)}(SitePlugin):\n"
        f"    name = {name!r}\n"
        f"    domains = [{domains_list}]\n"
        f"    description = {description!r}\n"
        '    fetcher = "http"\n\n'
        "    schema = Schema(\n"
        f"        container={container_literal},\n"
        "        fields=[\n"
        f"            {field_lines}\n"
        "        ],\n"
        "    )\n\n"
        "    def parse(self, page):\n"
        "        return self.schema.extract(page)\n"
    )


# --------------------------------------------------------------------------
# Server entry point
# --------------------------------------------------------------------------
def run_server(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    open_browser: bool = True,
    plugin_dirs: Optional[list[str]] = None,
    debug: bool = False,
) -> None:
    """Start the dashboard (blocking)."""
    app = create_app(plugin_dirs)
    url = f"http://{host}:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"\n  Arachne 控制台: {url}  (Ctrl+C 退出)\n")
    app.run(host=host, port=port, debug=debug, threaded=True, use_reloader=False)


if __name__ == "__main__":
    run_server()
