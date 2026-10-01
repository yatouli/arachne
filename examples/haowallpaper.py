"""haowallpaper.com 壁纸爬取示例。

结论：这个站**可以爬**，但分两档 ——
  * 缩略图 / 预览图 / 元数据：直接可下（本脚本演示这部分）
  * 高清原图（4096x2306，1.54MB）：需要「滑块验证 + AES 加密请求 + 下载签名」，
    属于较深的 JS 逆向，见文末说明。

用法：
    python examples/haowallpaper.py            # 抓首页前 N 张
    python examples/haowallpaper.py 3 10       # 从第 3 页开始，抓 10 张
"""

import os
import re
import sys

from arachne import Fetcher

# Windows GBK 控制台兼容：输出用 UTF-8，避免打印中文/符号时报错
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "https://haowallpaper.com"


def list_wallpaper_detail_ids(page_num: int = 1) -> list[str]:
    """首页（翻页）→ 壁纸详情页 ID 列表。"""
    url = BASE + "/" if page_num <= 1 else f"{BASE}/?page={page_num}"
    page = Fetcher.fetch(url, impersonate="chrome124")
    ids: list[str] = []
    for href in page.css("a::attr(href)").getall():
        m = re.search(r"/homeViewLook/(\d+)", href or "")
        if m and m.group(1) not in ids:
            ids.append(m.group(1))
    return ids


def get_wallpaper_meta(detail_id: str) -> dict:
    """详情页 → 标题 / 预览图 / 分辨率大小。"""
    page = Fetcher.fetch(f"{BASE}/homeViewLook/{detail_id}", impersonate="chrome124")
    title = page.css("title::text").get() or ""
    preview = None
    m = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', page.text)
    if m:
        preview = m.group(1)
    desc = ""
    m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]+)"', page.text)
    if m:
        desc = m.group(1)
    # og:description 形如「…分辨率：4096x2306…大小：1.54 MB…」
    resolution = re.search(r"([0-9]{3,6}\s*[x×]\s*[0-9]{3,6})", desc)  # 如 4096x2306
    size = re.search(r"大小[：:]\s*([0-9.]+ ?[KMG]B)", desc, re.I)
    return {
        "title": title,
        "preview": preview,
        "resolution": resolution.group(1) if resolution else None,
        "size": size.group(1) if size else None,
    }


def download(url: str, path: str) -> int:
    img = Fetcher.fetch(url, impersonate="chrome124")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(img.content)
    return len(img.content)


def main() -> None:
    start_page = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    detail_ids = list_wallpaper_detail_ids(start_page)
    print(f"第 {start_page} 页找到 {len(detail_ids)} 张壁纸，下载前 {limit} 张\n")

    saved = 0
    for detail_id in detail_ids[:limit]:
        meta = get_wallpaper_meta(detail_id)
        if not meta["preview"]:
            print(f"✗ {detail_id} 无预览图")
            continue
        path = f"wallpapers/{detail_id}.jpg"
        size = download(meta["preview"], path)
        saved += 1
        print(f"✓ {meta['title']}  [{meta['resolution'] or '?'} / {meta['size'] or '?'}]")
        print(f"    已保存 {path} ({size} B)")

    print(f"\n完成，共 {saved} 张（预览图）。")


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# 高清原图说明（JS 逆向方向）
# ---------------------------------------------------------------------------
# 原图下载接口：/link/common/file/downloadFile/{imgId}  返回 401（openresty）。
# 从站内 JS 逆向出的下载流程：
#   1. 点击「下载」→ 弹出 SlideVerify 滑块验证
#   2. POST /pc/public/slider/validate ，请求体经 encryptValue() AES 加密
#   3. 验证通过后 emit("download")，携带签名访问 downloadFile
# 因此要拿到原图需要：提取 AES 密钥 + 过滑块验证 + 还原下载签名。
# 如有需要可在此基础上继续逆向（arachne.js_reverse.SignatureCracker 等工具）。
