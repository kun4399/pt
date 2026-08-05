#!/usr/bin/env python3
"""
TJUPT 种子搜索脚本
支持关键字搜索、分类过滤、排序、分页。

用法:
    python3 tjupt_search.py "关键字"
    python3 tjupt_search.py "关键字" --cat 401 --sort seeders
    python3 tjupt_search.py "关键字" --download 1
"""

import argparse
import os
import re
import sys
from html import unescape
from urllib.parse import urljoin

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tjupt_login import login, BASE_URL

CATEGORIES = {
    401: "电影", 402: "剧集", 403: "综艺", 404: "资料",
    405: "动漫", 406: "音乐", 407: "体育", 408: "软件",
    409: "游戏", 410: "其他", 411: "纪录片", 412: "移动视频",
}

SEARCH_AREAS = {"title": 0, "subtitle": 2, "uploader": 3, "imdb": 4, "douban": 5}
SEARCH_MODES = {"and": 0, "or": 1, "exact": 2}
SORT_FIELDS = {
    "default": 0, "title": 1, "comments": 3, "time": 4,
    "size": 5, "snatched": 6, "seeders": 7, "leechers": 8, "uploader": 9,
}

# ── 解析 ────────────────────────────────────────────────────────────

def parse_torrent_table(html: str) -> list:
    """
    解析种子列表，返回 [{id, category, title, subtitle, url, download_url,
    comments, upload_time, size, size_unit, seeders, leechers, snatched, uploader}]
    """
    CAT_CLASS_MAP = {
        "c_movies": "电影", "c_tvseries": "剧集", "c_tvshows": "综艺",
        "c_documentary": "资料", "c_anime": "动漫", "c_music": "音乐",
        "c_sports": "体育", "c_software": "软件", "c_games": "游戏",
        "c_other": "其他", "c_doc": "纪录片", "c_mobile": "移动视频",
    }

    results = []

    # 以 details.php 标题链接为锚点，排除 dllist/viewsnatches/comment 等辅助链接
    all_links = list(re.finditer(
        r'href="(details\.php\?id=(\d+)[^"]*)"[^>]*>\s*(.*?)\s*</a>',
        html, re.DOTALL
    ))
    detail_matches = []
    seen_ids = set()
    for m in all_links:
        href = m.group(1)
        tid = m.group(2)
        # 跳过 seeders/leechers/snatches/comment 链接
        if any(x in href for x in ['dllist', 'viewsnatches', 'comment']):
            continue
        if tid in seen_ids:
            continue
        seen_ids.add(tid)
        detail_matches.append(m)

    for idx, dm in enumerate(detail_matches):
        t = {}
        t["id"] = int(dm.group(2))
        t["url"] = urljoin(BASE_URL, f"details.php?id={t['id']}&hit=1")
        t["title"] = unescape(re.sub(r'<[^>]+>', '', dm.group(3)).strip())

        # 向前搜索分类图标
        search_start = detail_matches[idx - 1].end() if idx > 0 else 0
        prefix = html[search_start:dm.start()]
        cat_cls = re.search(r'<img[^>]*class="(c_\w+)"', prefix, re.IGNORECASE)
        t["category"] = CAT_CLASS_MAP.get(cat_cls.group(1), "?") if cat_cls else "?"

        # 确定条目范围: 从分类图标到下一条目的分类图标
        if cat_cls:
            chunk_start = search_start + cat_cls.start()
        else:
            chunk_start = dm.start()
        if idx + 1 < len(detail_matches):
            # 下一条目的分类图标
            next_prefix = html[dm.end():detail_matches[idx + 1].start()]
            next_cat = re.search(r'<img[^>]*class="(c_\w+)"', next_prefix, re.IGNORECASE)
            if next_cat:
                chunk_end = dm.end() + next_cat.start()
            else:
                chunk_end = detail_matches[idx + 1].start()
        else:
            pag = html.find('上一页', dm.end())
            chunk_end = pag if pag != -1 else len(html)
        chunk = html[chunk_start:chunk_end]

        # ── 副标题 ──
        sub_m = re.search(r'</a>\s*<br\s*/?>\s*([^<]+)', chunk, re.DOTALL)
        t["subtitle"] = unescape(re.sub(r'<[^>]+>', '', sub_m.group(1)).strip()) if sub_m else ""

        # ── 下载链接 ──
        dl_m = re.search(r"href=['\"]?(download\.php\?id=\d+)['\"]?", chunk, re.IGNORECASE)
        t["download_url"] = urljoin(BASE_URL, dl_m.group(1)) if dl_m else \
            urljoin(BASE_URL, f"download.php?id={t['id']}")

        # ── 嵌套表后的数据列 ──
        # 找到 torrentname 嵌套表的结束位置 (第一个 </table> 在 chunk 中)
        # 不使用 rfind，因为 chunk 可能包含后续种子的嵌套表
        tn_pos = chunk.find('torrentname')
        if tn_pos != -1:
            # 从 torrentname 开始位置找第一个 </table>
            nested_end = chunk.find('</table>', tn_pos)
            if nested_end != -1:
                tail = chunk[nested_end + 8:]
            else:
                tail = chunk
        else:
            tail = chunk

        tds = re.findall(r'<td[^>]*class="rowfollow[^"]*"[^>]*>(.*?)</td>', tail, re.DOTALL)

        num_vals = []
        time_val = ""
        size_val = 0.0
        size_unit = ""
        uploader_val = "匿名"

        for td in tds:
            text = re.sub(r'<br\s*/?>', '\n', td, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'&nbsp;', ' ', text).strip()
            if not text:
                continue

            # 时间: YYYY-MM-DD 或 X小时/分钟前
            tm = re.search(r'(\d{4}-\d{2}-\d{2})\s*(?:\n\s*)?(\d{2}:\d{2}:\d{2})?', text)
            if tm:
                time_val = tm.group(1)
                if tm.group(2):
                    time_val += " " + tm.group(2)
                continue
            # 相对时间: "X 小时前" "X 分钟前" 等
            rel_tm = re.search(r'(\d+)\s*(小时|分钟|天|月|年)前', text)
            if rel_tm:
                time_val = f"{rel_tm.group(1)}{rel_tm.group(2)}前"
                continue

            # 大小: 数字\n单位
            sm = re.search(r'([\d,.]+)\s*\n\s*(TiB|GiB|MiB|KiB|TB|GB|MB|KB)', text, re.IGNORECASE)
            if sm:
                size_val = float(sm.group(1).replace(",", ""))
                size_unit = sm.group(2)
                continue

            # 发布者
            um = re.search(r'<a[^>]*href="userdetails[^"]*"[^>]*>\s*(.*?)\s*</a>', td, re.DOTALL)
            if um:
                uploader_val = unescape(re.sub(r'<[^>]+>', '', um.group(1)).strip())
                continue
            am = re.search(r'<i>\s*([^<]+)\s*</i>', td)
            if am:
                uploader_val = am.group(1).strip()
                continue

            # 纯数字
            nm = re.search(r'^(\d[\d,]*)$', text)
            if nm:
                num_vals.append(int(nm.group(1).replace(",", "")))

        t["comments"] = num_vals[0] if len(num_vals) > 0 else 0
        t["seeders"] = num_vals[1] if len(num_vals) > 1 else 0
        t["leechers"] = num_vals[2] if len(num_vals) > 2 else 0
        t["snatched"] = num_vals[3] if len(num_vals) > 3 else 0
        t["upload_time"] = time_val
        t["size"] = size_val
        t["size_unit"] = size_unit
        t["uploader"] = uploader_val

        results.append(t)

    return results


def parse_pagination(html: str) -> dict:
    info = {"total_results": 0, "total_pages": 0, "per_page": 100}
    last_pages = re.findall(
        r'<a[^>]*href="[^"]*page=(\d+)[^"]*">\s*<b>\s*[\d,]+\s*-\s*(\d+)\s*</b>', html
    )
    if last_pages:
        info["total_pages"] = max(int(p) for p, _ in last_pages) + 1
        info["total_results"] = max(int(e) for _, e in last_pages)
    return info

# ── 搜索 API ────────────────────────────────────────────────────────

def search(keyword="", categories=None, search_area="title", search_mode="and",
           sort_by="default", sort_order="desc", page=0, incldead=0,
           session=None) -> dict:
    if session is None:
        session = login(verbose=False)
        if not session:
            return {"results": [], "pagination": {}, "error": "登录失败"}

    params = {}
    if keyword:
        params["search"] = keyword
    if categories:
        params["cat[]"] = [str(c) for c in categories]
    area_id = SEARCH_AREAS.get(search_area, 0)
    if area_id:
        params["search_area"] = area_id
    mode_id = SEARCH_MODES.get(search_mode, 0)
    if mode_id:
        params["search_mode"] = mode_id
    sort_id = SORT_FIELDS.get(sort_by, 0)
    if sort_id:
        params["sort"] = sort_id
    if sort_order == "asc":
        params["type"] = "asc"
    if page > 0:
        params["page"] = page
    if incldead > 0:
        params["incldead"] = incldead

    try:
        resp = session.get(f"{BASE_URL}/torrents.php", params=params, timeout=30)
    except requests.RequestException as e:
        return {"results": [], "pagination": {}, "error": str(e)}
    if resp.status_code != 200:
        return {"results": [], "pagination": {}, "error": f"HTTP {resp.status_code}"}
    html = resp.text
    if "login.php" in str(resp.url):
        return {"results": [], "pagination": {}, "error": "登录已过期"}

    return {
        "results": parse_torrent_table(html),
        "pagination": parse_pagination(html),
        "url": str(resp.url),
    }


def download_torrent(tid, save_path=None, session=None) -> tuple:
    if session is None:
        session = login(verbose=False)
        if not session:
            return False, "登录失败"
    try:
        resp = session.get(f"{BASE_URL}/download.php?id={tid}", timeout=30)
    except requests.RequestException as e:
        return False, str(e)
    if resp.status_code != 200 or "<html" in resp.text[:200].lower():
        return False, f"下载失败 (HTTP {resp.status_code})"

    cd = resp.headers.get("Content-Disposition", "")
    fn_m = re.search(r'filename[^;=\n]*=["\']?([^"\'\n;]+)', cd)
    filename = fn_m.group(1) if fn_m else f"tjupt_{tid}.torrent"
    if save_path is None:
        save_path = os.path.join(os.getcwd(), filename)
    elif os.path.isdir(save_path):
        save_path = os.path.join(save_path, filename)
    with open(save_path, "wb") as f:
        f.write(resp.content)
    return True, save_path

# ── CLI ─────────────────────────────────────────────────────────────

def fmt_size(size, unit):
    return f"{size:,.2f} {unit}" if size else "N/A"


def print_results(data, fmt="table"):
    results = data.get("results", [])
    pg = data.get("pagination", {})
    if data.get("error"):
        print(f"✗ {data['error']}")
        return
    if not results:
        print("未找到匹配的种子。")
        return

    if fmt == "table":
        total = pg.get("total_results", len(results))
        print(f"\n{'=' * 100}")
        print(f"共 {total:,} 条 | 本页 {len(results)} 条")
        print(f"{'=' * 100}")
        for i, t in enumerate(results):
            print(f"\n─ [{i+1}] [{t['category']}] {t['title']}")
            if t.get("subtitle"):
                s = t["subtitle"][:120]
                print(f"   副题: {s}{'...' if len(t.get('subtitle', '')) > 120 else ''}")
            print(f"   大小: {fmt_size(t['size'], t['size_unit'])}  |  "
                  f"时间: {t['upload_time'] or 'N/A'}  |  评论: {t['comments']}")
            print(f"   做种: {t['seeders']}  |  下载: {t['leechers']}  |  "
                  f"完成: {t['snatched']}  |  发布: {t['uploader']}")
            print(f"   详情: {t['url']}")
            print(f"   下载: {t['download_url']}")
    else:
        for i, t in enumerate(results):
            print(
                f"[{i+1}] [{t['category']}] {t['title']} "
                f"| {fmt_size(t['size'], t['size_unit'])} "
                f"| S:{t['seeders']} L:{t['leechers']} C:{t['snatched']} "
                f"| {t.get('upload_time', '')[:10]} "
                f"| {t['download_url']}"
            )


def main():
    p = argparse.ArgumentParser(
        description="TJUPT 种子搜索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "星际穿越"                 基本搜索
  %(prog)s "2160p" --cat 401         搜索电影分类
  %(prog)s "test" --sort seeders      按做种数排序
  %(prog)s "test" --page 2           第3页
  %(prog)s "test" --download 1       下载第1个种子

分类: 401=电影 402=剧集 403=综艺 404=资料 405=动漫
      406=音乐 407=体育 408=软件 409=游戏 410=其他
      411=纪录片 412=移动视频
""")
    p.add_argument("keyword", nargs="?", default="", help="搜索关键字")
    p.add_argument("--cat", type=int, nargs="+", help="分类 ID")
    p.add_argument("--area", choices=list(SEARCH_AREAS.keys()), default="title")
    p.add_argument("--mode", choices=list(SEARCH_MODES.keys()), default="and")
    p.add_argument("--sort", choices=list(SORT_FIELDS.keys()), default="default")
    p.add_argument("--order", choices=["asc", "desc"], default="desc")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--incldead", type=int, choices=[0, 1, 2], default=0)
    p.add_argument("--download", type=int, metavar="N", help="下载第N个结果")
    p.add_argument("--output", choices=["table", "simple"], default="table")
    p.add_argument("--dl-dir", help="下载目录")
    args = p.parse_args()

    print("登录中...", end=" ", flush=True)
    session = login(verbose=False)
    if not session:
        print("✗")
        sys.exit(1)
    print("✓")

    print("搜索中...", end=" ", flush=True)
    data = search(
        keyword=args.keyword, categories=args.cat,
        search_area=args.area, search_mode=args.mode,
        sort_by=args.sort, sort_order=args.order,
        page=args.page, incldead=args.incldead,
        session=session,
    )
    print("✓")

    if args.download is not None:
        results = data.get("results", [])
        if args.download < 1 or args.download > len(results):
            print(f"✗ 无效序号 (共 {len(results)} 条)")
            sys.exit(1)
        t = results[args.download - 1]
        print(f"\n下载: {t['title'][:80]}")
        ok, result = download_torrent(t["id"], args.dl_dir, session)
        print(f"{'✓' if ok else '✗'} {result}")
        return

    print_results(data, args.output)


if __name__ == "__main__":
    main()
