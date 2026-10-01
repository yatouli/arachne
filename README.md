# Arachne 🕷️

一个 **AI 驱动的自适应爬虫框架**，参考 [Scrapling](https://github.com/D4Vinci/Scrapling) 的设计思想，把现代爬虫所需的全部能力打包在一个库里：

- 🔌 **站点内容插件系统** —— 为每个网站写一次插件，按 URL 自动匹配复用
- 🛡️ **反反爬机制** —— TLS/HTTP2 指纹伪装、浏览器指纹伪装、代理轮换、自适应限速退避、风控/验证码检测
- 🔓 **JS 逆向工具** —— 内嵌 JS 执行引擎、XHR 捕获、API 端点发现、签名函数定位与调用
- 🎯 **快速针对不同网站** —— 自适应解析（网站改版后自动重定位元素）、Schema 声明式提取、Scrapy 风格 Spider

---

## 目录

- [安装](#安装)
- [快速开始](#快速开始)
- [插件系统（自定义爬取内容插件）](#插件系统)
- [反反爬机制](#反反爬机制)
- [JS 逆向（js逆向）](#js-逆向)
- [Spider 爬取框架](#spider-爬取框架)
- [自适应解析与 Schema](#自适应解析与-schema)
- [AI 集成](#ai-集成)
- [命令行工具](#命令行工具)
- [项目结构](#项目结构)
- [测试](#测试)
- [合规声明](#合规声明)

---

## 安装

```bash
# 基础（解析 + httpx 回退 HTTP）
pip install -e . --no-build-isolation

# 反反爬 HTTP（curl_cffi 的 TLS 指纹伪装）+ 浏览器（Playwright）
pip install -e ".[stealth]" --no-build-isolation
python -m playwright install chromium

# JS 逆向（内嵌 V8，免装 Node）
pip install "py_mini_racer"

# AI 辅助生成选择器/Schema
pip install "openai"

# 全量
pip install -e ".[all]" --no-build-isolation
```

> 环境依赖均为**可选**：缺 `curl_cffi` 时回退 `httpx`（仅失去 TLS 指纹伪装），缺 `playwright` 时
> `DynamicFetcher/StealthyFetcher` 不可用，缺 JS 引擎时回退 Node。

---

## 快速开始

```python
from arachne import Fetcher

# 一行抓取，自动伪装 Chrome 124 的 TLS/HTTP2 指纹
page = Fetcher.fetch("https://example.com", impersonate="chrome124")

print(page.css("title::text").get())   # 选择器
print(page.markdown())                 # 干净的 LLM-ready Markdown
print(page.is_blocked())               # 风控检测
```

针对结构可能变化的网站，用**自适应解析**保存元素“指纹”，改版后仍能找回：

```python
from arachne.parsing import ElementFingerprint, relocate

page = Fetcher.fetch("https://example.com")
h1 = page.css("h1").first
fingerprint = ElementFingerprint.from_element(h1)   # 记录元素特征

# ... 网站改版后，用新页面重定位 ...
matches = relocate(new_page.selector, fingerprint, threshold=0.4)
print(matches.first.text())
```

---

## 插件系统

插件 = 匹配规则 + 解析逻辑。把它放进 `plugins/` 目录（或注册为 entry point），框架会按 URL 自动挑选。

```python
# plugins/hackernews.py
from arachne.plugins import SitePlugin, plugin

@plugin
class HackerNewsPlugin(SitePlugin):
    name = "hackernews"
    domains = ["news.ycombinator.com"]      # 按域名匹配
    url_patterns = [r"/item\?id="]          # 或按 URL 正则匹配
    fetcher = "http"                        # http | dynamic | stealth
    priority = 0                            # 多个插件命中时，优先级高者胜出

    def parse(self, page):
        return page.css("tr.athing").as_dicts(
            title=".titleline a::text",
            url=".titleline a::attr(href)",
            rank=".rank::text",
        )
```

使用插件（自动匹配）：

```python
from arachne.engine import Arachne

engine = Arachne(plugin_dirs=["plugins"])     # 加载 plugins/ 目录
items = engine.scrape("https://news.ycombinator.com")  # 自动命中并解析
```

也支持**声明式 Schema 插件**（见 [Schema](#自适应解析与-schema) 与
`plugins/generic_product.py`），以及 `before_fetch()` 钩子修改请求头/参数。

`pyproject.toml` 支持第三方包通过 entry point 注册：

```toml
[project.entry-points."arachne.plugins"]
my_site = "my_package.plugins"
```

---

## 反反爬机制

| 能力 | 说明 |
|------|------|
| **TLS/HTTP2 指纹伪装** | `curl_cffi` 伪装 Chrome/Safari/Firefox/Edge 的 TLS 与 HTTP2 指纹，是纯 HTTP 反爬最强手段 |
| **浏览器指纹伪装** | `StealthyFetcher` 抹除 `navigator.webdriver`、伪造 `plugins`/`window.chrome`/客户端提示，UA/视口/时区/语言保持一致 |
| **代理轮换** | `ProxyRotator`：`cyclic` / `random` / `sticky`（失败自动切换） |
| **自适应限速退避** | `AutoThrottle`：按域名独立调速，被拦时倍增延迟、尊重 `Retry-After`，恢复后逐渐回落 |
| **风控/验证码检测** | `detect_block()` 识别 Cloudflare Turnstile / hCaptcha / reCAPTCHA / DataDome / 403 / 429 |
| **挑战自动解决** | `StealthyFetcher` 遇到 Turnstile 会等待浏览器自动过关后重读页面 |
| **自动回退** | 普通请求被拦时可 `stealth_fallback=True` 升级到隐身浏览器 |

```python
from arachne import Fetcher, StealthyFetcher
from arachne.antidetect import build_headers, ProxyRotator, AutoThrottle

# 三种取数器，接口一致
page = Fetcher.fetch(url, impersonate="chrome124", proxies=["http://u:p@host:port"])
page = StealthyFetcher.fetch(url, headless=True, challenge_wait=15)

# 手动构造一致的头
headers = build_headers("chrome124", referer="https://google.com")

# 代理轮换
rotator = ProxyRotator(["http://p1", "http://p2"], strategy="cyclic")
print(rotator.next())

# 自适应限速（Spider 内部自动使用）
throttle = AutoThrottle(start_delay=1.0, max_delay=60.0)
throttle.report_block(url)      # 被拦 → 延迟翻倍
```

---

## JS 逆向

### 内嵌 JS 引擎（无需 Node）

```python
from arachne.js_reverse import JsEngine

with JsEngine() as js:                 # 自动选择 py_mini_racer(V8) / node / quickjs
    js.run("function md5(s){ return 'md5:' + s; }")
    print(js.call("md5", "hello"))     # 'md5:hello'
```

### 签名函数定位与复现（签名破解工作流）

```python
from arachne.js_reverse import SignatureCracker, detect_hash_algorithms
from arachne.js_reverse.engine import JsEngine

site_js = open("site.js").read()       # 1. 拿到页面 JS
cracker = SignatureCracker(js=site_js, engine=JsEngine())
cracker.find_candidates()              # 2. 自动定位 sign/token/encrypt/md5 等候选函数
print(cracker.candidates)
print(detect_hash_algorithms(site_js)) # 检测 md5/sha256/hmac/aes/rsa

# 3. 用已知样本反推：哪个函数能算出观察到的签名？
results = cracker.crack(timestamp, payload, observed="<抓包看到的签名>")
for r in results:
    print(r.function_name, r.value, r.matches)
```

### XHR 捕获与 API 端点发现（免逆向直连接口）

```python
from arachne.js_reverse import discover_api_endpoints, find_embedded_state

# 从 HTML/JS 文本里找出 API 地址
print(discover_api_endpoints(page.text, page.url))

# 提取 __NEXT_DATA__ / __INITIAL_STATE__ / window.__NUXT__ 等内嵌 JSON
state = find_embedded_state(page)

# 浏览器抓包：捕获页面加载时的所有 XHR/fetch 响应
page = StealthyFetcher.fetch(url, capture_xhr=r"/api/")
for xhr in page.captured_xhr:
    print(xhr.url, xhr.json())
```

---

## Spider 爬取框架

Scrapy 风格的异步 Spider：并发、去重、robots.txt、自适应限速、流式输出。

```python
from arachne.spider import Spider, CrawlSpider, Rule, LinkExtractor

class QuotesSpider(Spider):
    name = "quotes"
    start_urls = ["https://quotes.toscrape.com/"]
    custom_settings = {"concurrency": 4, "auto_throttle": True}

    async def parse(self, response):
        for q in response.css(".quote"):
            yield {
                "text": q.css(".text::text").get(),
                "author": q.css(".author::text").get(),
                "tags": q.css(".tag::text").getall(),
            }
        next_page = response.css("li.next a::attr(href)").get()
        if next_page:
            yield response.follow(next_page, callback=self.parse)

result = QuotesSpider().run()
print(result.stats.items, result.stats.duration)
result.to_json()          # 也支持 to_jsonl() / to_csv()
```

- `CrawlSpider` + `Rule(LinkExtractor(...), follow=True)`：规则式全站爬取
- 单个 `Request` 可用 `fetcher="dynamic"` / `fetcher="stealth"` 指定不同取数器
- `stream()`：`async for item in spider.stream()` 实时流式产出

---

## 自适应解析与 Schema

**声明式 Schema**（同时是文档，可序列化/复用）：

```python
from arachne.parsing import Field, Schema

schema = Schema(
    container=".product",                                  # 每条记录的容器
    fields=[
        Field(name="title", selector="h3.title::text"),
        Field(name="price", selector=".price::text", type=float),   # 自动去 $ 转数值
        Field(name="url", selector="a::attr(href)"),
    ],
)
records = schema.extract(page)     # -> list[dict]
```

**自适应重定位**：`ElementFingerprint` 记录元素特征（标签/类/id/文本/结构），
`relocate()` 在新 DOM 里按加权相似度找回元素（见 `arachne/parsing/adaptive.py`）。

---

## AI 集成

接任意 OpenAI 兼容接口（OpenAI / 本地 vLLM / Ollama）自动生成选择器或直接抽取：

```python
from arachne.config import Settings
from arachne.ai import infer_schema, extract_fields

settings = Settings(llm_base_url="http://localhost:8000/v1", llm_model="qwen2.5")

schema = infer_schema(page, field_names=["title", "price"], container_hint=".product")
print(schema.extract(page))

data = extract_fields(page, {"title": "商品标题", "price": "数字价格"})
```

---

## 命令行工具

```bash
arachne fetch https://example.com                 # 打印 Markdown
arachne fetch https://example.com --stealth       # 隐身浏览器
arachne fetch URL -o out.html --impersonate chrome124 --proxy http://p:1

arachne extract URL --field title="title::text" --field links="a::attr(href)"

arachne plugins --dir plugins                     # 列出已注册插件
arachne js "6 * 7"                                # 内嵌引擎执行 JS
```

---

## Web 交互界面 🖥️

一条命令启动本地可视化控制台，自动打开浏览器：

```bash
arachne ui                       # 默认 http://127.0.0.1:8000
arachne ui --port 9000           # 指定端口
arachne ui --no-browser          # 不自动打开浏览器
```

界面功能：

- **抓取网页**：填 URL → 选取数器（HTTP/Dynamic/Stealth）→ 选浏览器指纹 → 填代理/XHR 正则 → 一键抓取
- **结果标签页**：数据（表格）/ 字段 / Markdown / 原始 HTML / XHR 捕获，并实时显示状态码、标题、命中插件、风控检测结果
- **按选择器提取字段**：无需写代码，动态添加「字段名 = CSS 选择器」行
- **智能正文提取**：勾选后自动识别标题/正文/主图/作者/时间（无需选择器，覆盖新闻/博客/文章页）
- **批量爬取**：填「列表页 URL + 详情链接正则（可留空自动识别）+ 字段（可留空自动正文）」即可翻页、并发抓取、并按图片字段自动下载图片
- **Sitemap 全站爬取**：填一个域名，自动从 robots.txt + 常见路径发现 sitemap.xml，递归解析后全站爬取
- **AI 智能提取**：接任意 OpenAI 兼容接口（Ollama/vLLM/OpenAI），用自然语言描述字段，AI 直接抽取
- **站点插件**：列出已注册插件；可视化表单（名称 + 域名 + 容器 + 字段）自动生成 Schema 插件，也支持直接粘贴完整插件代码
- **JS 逆向/执行**：内嵌引擎执行表达式或语句

实现是 Flask + 单页前端，零额外依赖（Flask 已内置环境）。后端 API：
`/api/status`、`/api/scrape`、`/api/crawl`、`/api/sitemap`、`/api/ai_extract`、
`/api/plugins`（GET/POST）、`/api/js`。

```python
# 也可在代码里直接启动
from arachne.web.server import run_server
run_server(host="127.0.0.1", port=8000)
```

### 智能识别（无需选择器，覆盖大部分网站）

```python
from arachne import Fetcher

page = Fetcher.fetch(url, impersonate="chrome124")

article = page.readable()      # 自动正文：标题/正文/主图/作者/时间
items = page.list_items()      # 自动列表：识别重复卡片，提取链接/标题/图片

# Sitemap 全站爬取
from arachne.spider import SitemapSpider, discover_sitemap_urls
sitemaps = discover_sitemap_urls("https://example.com")
result = SitemapSpider(sitemap_urls=sitemaps, limit=50).run()

# AI 抽取（需配置 ARACHNE_LLM_BASE_URL / ARACHNE_LLM_API_KEY）
from arachne.ai import extract_fields
fields = extract_fields(page, {"title": "文章标题", "author": "作者"})
```

---

## 项目结构

```
arachne/
├── arachne/
│   ├── engine.py          # 高层入口：插件匹配 + 取数
│   ├── page.py            # Page：统一结果对象 + HTML→Markdown
│   ├── config.py          # Settings（贯穿各层）
│   ├── fetchers/          # http(隐身) / dynamic(浏览器) / stealth(反检测)
│   ├── antidetect/        # 指纹、头、代理、会话、限速、风控检测
│   ├── js_reverse/        # JS 引擎、XHR、签名破解
│   ├── parsing/           # 选择器、自适应重定位、Schema
│   ├── plugins/           # 站点插件基类 + 注册/发现
│   ├── spider/            # Spider / CrawlSpider / 调度器
│   ├── pipeline/          # Item + JSON/JSONL/CSV/Parquet 导出
│   ├── ai/                # LLM 客户端 + 选择器/Schema 生成
│   ├── web/               # Web 交互界面（Flask + 单页前端）
│   └── cli.py
├── plugins/               # 示例插件（hackernews / generic_product）
├── examples/              # 示例脚本
└── tests/                 # 单元 + 端到端测试
```

---

## 测试

```bash
python tests/test_core.py     # 解析/自适应/风控/JS/插件/智能识别（11 项）
python tests/test_e2e.py      # 本地服务器端到端（fetch + spider + 插件）
python tests/test_web.py      # Web 界面（状态/抓取/批量/JS/插件创建，4 项）
python tests/test_sitemap.py  # Sitemap 发现/解析/爬取
pytest                        # 同样兼容
```

---

## 合规声明

本框架仅供**合法授权**的数据采集、学习与研究使用。请遵守目标网站的
`robots.txt`、服务条款及当地法律法规，控制抓取频率，不要爬取个人隐私或受版权保护的内容。
使用者需对自身行为负责。
