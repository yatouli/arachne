"""用 Arachne 的 Spider 框架批量爬取 haowallpaper.com 壁纸。

三种用法里，批量爬取最适合用 Spider（并发 + 去重 + 自适应限速）。

用法：
    python examples/haowallpaper_spider.py        # 爬第 1 页
    python examples/haowallpaper_spider.py 3      # 爬 1~3 页
"""

import os
import re
import sys

from arachne.spider import Spider

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://haowallpaper.com"


class WallpaperSpider(Spider):
    name = "haowallpaper"
    custom_settings = {
        "concurrency": 4,       # 4 个并发
        "auto_throttle": True,  # 自适应限速，被拦会自动降速
        "robots_obey": False,
    }

    def __init__(self, pages: int = 1, download: bool = True, out_dir: str = "wallpapers", **kw):
        # 首页 + 翻页
        self.start_urls = [BASE + "/"] + [f"{BASE}/?page={i}" for i in range(2, pages + 1)]
        self.do_download = download
        self.out_dir = out_dir
        super().__init__(**kw)

    async def parse(self, response):
        """列表页：提取每个壁纸的详情页链接。"""
        for href in response.css("a::attr(href)").getall():
            m = re.search(r"/homeViewLook/(\d+)", href or "")
            if m:
                yield response.follow(f"/homeViewLook/{m.group(1)}", callback=self.parse_item)

    async def parse_item(self, response):
        """详情页：提取元数据 + 下载预览图。"""
        title = response.css("title::text").get()

        preview = None
        m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', response.text)
        if m:
            preview = m.group(1)

        desc = ""
        m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', response.text)
        if m:
            desc = m.group(1)

        resolution = re.search(r"([0-9]{3,6}\s*[x×]\s*[0-9]{3,6})", desc)  # 如 4096x2306
        size = re.search(r"大小[：:]\s*([0-9.]+ ?[KMG]B)", desc, re.I)

        # 用 Spider 自带的取数器异步下载图片（不阻塞事件循环）
        if preview and self.do_download:
            detail_id = re.search(r"/homeViewLook/(\d+)", response.url).group(1)
            os.makedirs(self.out_dir, exist_ok=True)
            img = await self._fetcher_for("http").afetch(preview)
            with open(f"{self.out_dir}/{detail_id}.jpg", "wb") as fh:
                fh.write(img.content)

        yield {
            "title": title,
            "resolution": resolution.group(1) if resolution else None,
            "size": size.group(1) if size else None,
            "preview": preview,
        }


if __name__ == "__main__":
    pages = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    spider = WallpaperSpider(pages=pages)
    result = spider.run()
    print(f"\n抓取完成：{result.stats.items} 条，耗时 {result.stats.duration:.1f}s，"
          f"被拦 {result.stats.blocked} 次，错误 {result.stats.errors} 次")
    for item in result.items[:5]:
        print(f"  {item['title']}  [{item['resolution']} / {item['size']}]")
