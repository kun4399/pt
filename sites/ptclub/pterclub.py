#!/usr/bin/env python3
"""
PTerClub (pterclub.net) 搜索脚本
=================================
使用浏览器导出的 Cookie 进行搜索，无需 Chromium/浏览器。

用法:
  python3 pterclub.py search <关键词>        # 搜索种子
  python3 pterclub.py search <关键词> -n 20  # 最多 20 条
  python3 pterclub.py search <关键词> --json # JSON 格式
  python3 pterclub.py check                  # 检查 Cookie 有效性

前置条件:
  ./cookies.json  — 从浏览器导出的 cookie（放在脚本同目录下）

环境: pip install requests beautifulsoup4 lxml
"""

import json
import os
import re
import sys
import argparse
from pathlib import Path
from urllib.parse import urljoin

import requests

# 确保能 import 项目根的 common 包
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SITE_DIR, "..", ".."))
for _p in (_SITE_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import constants, cookies as cookie_util, env, format as fmt, http

# ── 常量 ──────────────────────────────────────────────────
BASE_URL      = "https://pterclub.net"
TORRENTS_URL  = f"{BASE_URL}/torrents.php"
INDEX_URL     = f"{BASE_URL}/index.php"

SCRIPT_DIR    = Path(__file__).resolve().parent
COOKIE_FILE   = SCRIPT_DIR / "cookies.json"


# ── 工具函数 ──────────────────────────────────────────────

human_size = fmt.human_size
human_time = fmt.human_time


# ── Cookie 管理 (实现见 common.cookies) ───────────────────

def load_cookies() -> list[dict] | None:
    """读取浏览器导出的 cookies.json,失败返回 None。"""
    return cookie_util.load_browser_json(COOKIE_FILE)


def create_session(proxy: str = "") -> requests.Session:
    """带浏览器 cookie 的会话(UA 见 common.constants)。

    proxy: 显式代理(如 http://127.0.0.1:7890);空串时不读环境变量
    (make_session 的 trust_env=False),即直连。
    """
    session = http.make_session(proxy=proxy, ua=constants.UA_CHROME_X11_131)
    cookies = load_cookies()
    if cookies:
        cookie_util.inject_browser_cookies(session, cookies)
    return session


def check_login(proxy: str = "") -> bool:
    """检查 cookie 是否有效 (页面含未登录 → False; 含 usercp.php/控制面板 → True)。"""
    return http.is_logged_in(create_session(proxy), INDEX_URL,
                             fail_keywords=("未登录",),
                             success_keywords=("usercp.php", "控制面板"),
                             timeout=15)


# ── 搜索 ──────────────────────────────────────────────────

def parse_torrent_row(cells, passkey: str = "") -> dict | None:
    """
    解析种子表格中的一行（16 列）。

    列结构:
      [0]  类型图标 (img alt: 电影/剧集/音乐...)
      [1]  标题+标签 (details.php 链接)
      [2]  预览图
      [3]  标题/副标题 (另一组)
      [4-5] 空
      [6]  下载链接
      [7]  书签/RSS
      [8]  评分 (IMDb/豆瓣)
      [9]  评论数
      [10] 存活时间
      [11] 大小
      [12] 做种数
      [13] 下载数
      [14] 完成数
      [15] 发布者
    """
    if len(cells) < 12:
        return None

    from bs4 import BeautifulSoup

    # ── 类型（列 0: 图片 alt 文本） ──
    cats = []
    for img in cells[0].find_all("img"):
        alt = (img.get("alt") or img.get("title") or "").strip()
        if alt:
            cats.append(alt)
    category = " / ".join(cats) if cats else None

    # ── 标题 + 下载链接（列 1） ──
    title = None
    download_url = None
    details_url = None
    subtitle = None

    for a in cells[1].find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if "details.php" in href and not title:
            title = text
            details_url = urljoin(BASE_URL, href)
            # 从 href 提取种子 ID
            m = re.search(r'id=(\d+)', href)
            if m:
                download_url = f"{BASE_URL}/download.php?id={m.group(1)}"
                if passkey:
                    download_url += f"&passkey={passkey}"
        elif "download.php" in href:
            download_url = urljoin(BASE_URL, href)

    if not title:
        return None

    # ── 副标题（列 1 title 之后的文本） ──
    full_text = cells[1].get_text()
    if title and title in full_text:
        remaining = full_text.replace(title, "", 1).strip()
        if remaining:
            subtitle = remaining[:200]

    # ── 存活时间（列 10） ──
    alive_time = cells[10].get_text(strip=True) if len(cells) > 10 else None

    # ── 大小（列 11） ──
    size = cells[11].get_text(strip=True) if len(cells) > 11 else None

    # ── 做种/下载/完成（列 12-14） ──
    def _num(idx):
        try:
            return int(cells[idx].get_text(strip=True))
        except (ValueError, IndexError):
            return None

    seeders = _num(12)
    leechers = _num(13)
    completed = _num(14)

    # ── 发布者（列 15） ──
    uploader = cells[15].get_text(strip=True) if len(cells) > 15 else None

    # ── 标签（列 1 的 tag 链接） ──
    tags = []
    for a in cells[1].find_all("a"):
        href = a.get("href", "")
        text = a.get_text(strip=True)
        if "tag_" in href and text and text not in (title or ""):
            tags.append(text)

    return {
        "category": category,
        "title": title,
        "subtitle": subtitle,
        "tags": tags,
        "alive_time": alive_time,
        "size": size,
        "seeders": seeders,
        "leechers": leechers,
        "completed": completed,
        "uploader": uploader,
        "download_url": download_url,
        "details_url": details_url,
    }


def search(query: str, max_results: int = 50, proxy: str = "") -> list[dict]:
    """搜索种子，返回结构化结果"""
    from bs4 import BeautifulSoup

    session = create_session(proxy)

    # 先从任意页面获取 passkey（在下载链接中）
    passkey = ""
    try:
        resp = session.get(TORRENTS_URL, timeout=15)
        m = re.search(r'passkey=([a-f0-9]+)', resp.text)
        if m:
            passkey = m.group(1)
    except Exception:
        pass

    # 执行搜索
    params = {"search": query, "incldead": "0"}
    resp = session.get(TORRENTS_URL, params=params, timeout=30)

    if resp.status_code != 200:
        print(f"  HTTP {resp.status_code}")
        return []

    # 检查登录状态
    if "未登录" in resp.text:
        print("  Cookie 已失效，请重新从浏览器导出 cookie")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    # 找 torrents 表格
    torrent_table = None
    for t in soup.find_all("table"):
        if "torrent" in " ".join(t.get("class", [])).lower():
            torrent_table = t
            break

    if not torrent_table:
        print(f'  No results or page structure changed')
        return []

    results = []
    for row in torrent_table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 12:
            continue
        item = parse_torrent_row(cells, passkey)
        if item and item.get("title"):
            results.append(item)
            if len(results) >= max_results:
                break

    return results


# ── 输出 ──────────────────────────────────────────────────

def print_results(results: list[dict], query: str, json_fmt: bool = False):
    if json_fmt:
        print(json.dumps({"query": query, "count": len(results), "results": results},
                         indent=2, ensure_ascii=False))
        return

    if not results:
        print(f'\n  No results for [{query}]')
        return

    print(f'\n  [{query}] — {len(results)} result(s)\n')

    # 表头
    hdr = f"  {'Type':<12} {'Title':<44} {'Alive':<10} {'Size':<10} {'S':>5} {'L':>5} {'C':>5}"
    print(hdr)
    print("  " + "-" * (len(hdr)))

    for r in results:
        cat = (r["category"] or "?")[:12]
        title = (r["title"] or "?")[:42]
        alive = human_time(r["alive_time"])[:10]
        size = human_size(r["size"])[:10]
        s = str(r["seeders"]) if r["seeders"] is not None else "?"
        l = str(r["leechers"]) if r["leechers"] is not None else "?"
        c = str(r["completed"]) if r["completed"] is not None else "?"

        print(f"  {cat:<12} {title:<44} {alive:<10} {size:<10} {s:>5} {l:>5} {c:>5}")

        sub = r.get("subtitle")
        if sub:
            print(f"  {'':>12}  | {sub[:80]}")

        tags = r.get("tags")
        if tags:
            print(f"  {'':>12}  | Tags: {', '.join(tags[:8])}")

        dl = r.get("download_url")
        if dl:
            print(f"  {'':>12}  | 📥 {dl}")

        print()


# ── CLI ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="PTerClub 种子搜索 (Cookie 模式)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  %(prog)s search "4K HDR"         # 搜索 4K HDR 资源
  %(prog)s search "BluRay" -n 20   # 最多 20 条
  %(prog)s search "movie" --json   # JSON 输出
  %(prog)s check                   # 检查 Cookie 有效性
  %(prog)s --proxy http://127.0.0.1:7890 check   # 走代理(默认读 .env 全局代理)
        """,
    )
    parser.add_argument("--proxy", type=str, default=None,
                        help="HTTP 代理,如 http://127.0.0.1:7890"
                             "(默认读取 .env 的 HTTP_PROXY/HTTPS_PROXY)")
    sub = parser.add_subparsers(dest="cmd", help="命令")

    # search
    p = sub.add_parser("search", help="搜索种子")
    p.add_argument("keyword", help="搜索关键词")
    p.add_argument("-n", "--limit", type=int, default=50, help="最多条数")
    p.add_argument("--json", action="store_true", help="JSON 输出")

    # attendance
    sub.add_parser("attendance", help="签到（今日已签则显示状态）")

    # check
    sub.add_parser("check", help="检查 Cookie 是否有效")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return

    env.load_env()
    proxy = args.proxy if args.proxy is not None else env.get_proxy()
    if proxy:
        print(f"[代理] {proxy}")

    if args.cmd == "check":
        cookies = load_cookies()
        if not cookies:
            print("No cookie file found")
            print(f"Place exported cookies at: {COOKIE_FILE}")
            sys.exit(1)
        print(f"Loaded {len(cookies)} cookie(s)")
        if check_login(proxy):
            print("[OK] Cookie is valid!")
        else:
            print("[FAIL] Cookie expired or invalid")
            sys.exit(1)
        return

    if args.cmd == "attendance":
        cookies = load_cookies()
        if not cookies:
            print("No cookie file found")
            sys.exit(1)
        # TODO: 需要确定 #do-attendance 的 data-url（仅在未签到时可见）
        session = create_session(proxy)
        resp = session.get(f"{BASE_URL}/index.php", timeout=15)
        m = re.search(r'attendance-wrap[^>]*>([^<]+)', resp.text)
        if m:
            print(f"  {m.group(1).strip()}")
        else:
            print("  (签到接口待明天调试)")
        return

    if args.cmd == "search":
        cookies = load_cookies()
        if not cookies:
            print("No cookie file found. Export cookies from browser first.")
            print(f"See: {SCRIPT_DIR / 'export_cookies.js'}")
            sys.exit(1)

        print(f"\n  Searching: [{args.keyword}]")
        results = search(args.keyword, max_results=args.limit, proxy=proxy)
        print_results(results, args.keyword, json_fmt=args.json)


if __name__ == "__main__":
    main()
