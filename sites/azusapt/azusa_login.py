#!/usr/bin/env python3
"""
azusa.wiki 自动登录 + 种子搜索脚本
使用 ddddocr 识别验证码，复用 zjusport conda 环境

特性:
    - 每次运行都执行一次登录（登录前先检测剩余尝试次数）
    - 剩余尝试次数 ≤2：拒绝登录并警告，回退使用本地 cookie（若仍有效）
    - Cookie 自动持久化：登录成功保存到 azusa_cookies.txt，操作优先复用
    - 种子搜索：按关键词解析标题、大小、做种数、存活时间、下载链接等

用法:
    conda run -n zjusport python3 azusa_login.py --search "关键词"
    conda run -n zjusport python3 azusa_login.py --search "关键词" --page 2
    conda run -n zjusport python3 azusa_login.py --search "关键词" --concise
    conda run -n zjusport python3 azusa_login.py --search "汉化" --proxy http://127.0.0.1:7890
"""

import requests
import re
import sys
import time
import json
import argparse
import os
from pathlib import Path
from datetime import datetime
from bs4 import BeautifulSoup

# 确保能 import 项目根的 common 包
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SITE_DIR, "..", ".."))
for _p in (_SITE_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import config, cookies, env, http, sites

# ============================================================
# 配置区
# ============================================================
env.load_env()
USERNAME = env.get("AZUSA_USERNAME")
PASSWORD = env.get("AZUSA_PASSWORD")
BASE_URL = "https://azusa.wiki"
LOGIN_PAGE = f"{BASE_URL}/index.php?title=Special:UserLogin"
LOGIN_ACTION = f"{BASE_URL}/takelogin.php"
CAPTCHA_IMAGE_URL = f"{BASE_URL}/image.php"

# 最大尝试次数 (不要超过8次，否则触发风控)
MAX_ATTEMPTS = config.get_int("AZUSA_MAX_ATTEMPTS", 5)

# 文件路径
SCRIPT_DIR = Path(__file__).parent
COOKIE_FILE = sites.cookie_path("azusa") or SCRIPT_DIR / "azusa_cookies.txt"


# ============================================================
# Session 管理
# ============================================================

# ============================================================
# 登录模块
# ============================================================

def get_login_page(session):
    """
    获取登录页面，提取 csrf_token 和 imagehash。
    返回 (csrf_token, imagehash, attempts_remaining, error_message)
    - attempts_remaining: int, 剩余尝试次数（无法解析时为 -1）
    - error_message 不为 None 表示遇到致命错误（IP封锁等）
    """
    resp = session.get(LOGIN_PAGE, timeout=30)
    resp.raise_for_status()

    html = resp.text

    # --- 提取剩余尝试次数 ---
    # 格式: "你还有 [N] 次尝试机会"（数字常被 <b><font> 标签包裹，先去标签再匹配）
    attempts_match = re.search(r"还有\s*(?:\[(\d+)\]|(\d+))\s*次",
                               re.sub(r"<[^>]+>", "", html))
    if attempts_match:
        attempts_remaining = int(attempts_match.group(1) or attempts_match.group(2))
        print(f"  剩余尝试次数: {attempts_remaining}")
    else:
        attempts_remaining = -1  # 无法解析

    # --- 检查 IP 封锁 / 账号锁定 ---
    if "登录锁定" in html or "Login 锁定" in html:
        lock_match = re.search(r"Login 锁定！[^)]*\)", html)
        lock_reason = lock_match.group(0) if lock_match else "未知原因"
        print(f"[致命错误] {lock_reason}")
        return None, None, attempts_remaining, "IP封锁或账号锁定"

    if "禁用了你的IP地址" in html:
        print("[致命错误] IP 地址已被禁用，请等待风控解除后再试")
        return None, None, attempts_remaining, "IP已被禁用"

    if "最大错误尝试次数" in html:
        print("[致命错误] 登录错误次数已耗尽，IP 被临时封禁")
        return None, None, attempts_remaining, "登录错误次数耗尽"

    # --- 剩余尝试次数安全检查 ---
    if attempts_remaining >= 0 and attempts_remaining <= 2:
        print(f"[安全拒绝] 剩余尝试次数仅 {attempts_remaining} 次（≤2），"
              f"不执行登录以免触发风控封禁")
        return None, None, attempts_remaining, f"剩余次数不足(仅{attempts_remaining}次)"

    csrf_match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    csrf_token = csrf_match.group(1) if csrf_match else None

    hash_matches = re.findall(r'name="imagehash"[^>]*value="([^"]+)"', html)
    imagehash = hash_matches[0] if hash_matches else None

    if not csrf_token:
        print("[错误] 无法获取 csrf_token（页面结构可能已变化）")
        return None, None, attempts_remaining, "csrf_token缺失"

    if not imagehash:
        print("[错误] 无法获取 imagehash（页面结构可能已变化）")
        return None, None, attempts_remaining, "imagehash缺失"

    print(f"  csrf_token: {csrf_token[:20]}...")
    print(f"  imagehash:  {imagehash}")

    return csrf_token, imagehash, attempts_remaining, None


def get_captcha(session, imagehash):
    """获取验证码图片并识别"""
    img_url = f"{CAPTCHA_IMAGE_URL}?action=regimage&imagehash={imagehash}&secret="
    resp = session.get(img_url, timeout=30)
    resp.raise_for_status()

    img_bytes = resp.content
    if len(img_bytes) < 100:
        print("[错误] 验证码图片过小，可能获取失败")
        return None

    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)
    captcha_text = ocr.classification(img_bytes).strip()

    print(f"  验证码识别结果: '{captcha_text}'")
    return captcha_text


def do_login(session, csrf_token, imagehash, captcha_text):
    """提交登录表单"""
    post_data = {
        "csrf_token": csrf_token,
        "username": USERNAME,
        "password": PASSWORD,
        "imagestring": captcha_text,
        "imagehash": imagehash,
        "logout": "15",
        "securelogin": "yes",
        "ssl": "yes",
        "trackerssl": "yes",
    }

    resp = session.post(
        LOGIN_ACTION,
        data=post_data,
        timeout=30,
        allow_redirects=True,
    )

    return resp


def check_login_success(resp, session):
    """检查是否登录成功"""
    html = resp.text

    # 致命错误（IP封锁等，不应继续重试）
    fatal_patterns = [
        ("IP 被禁用", r"禁用了你的IP地址"),
        ("账号锁定", r"Login 锁定|登录锁定"),
        ("次数耗尽", r"最大错误尝试次数"),
    ]
    for name, pattern in fatal_patterns:
        if re.search(pattern, html, re.I):
            print(f"  [致命] 检测到: {name}")
            return "fatal"

    fail_patterns = [
        ("验证码错误", r"验证码错误|验证码不正确|验证码输入错误"),
        ("登录失败", r"登录失败|用户名或密码错误|密码错误"),
    ]

    for name, pattern in fail_patterns:
        if re.search(pattern, html, re.I):
            print(f"  检测到失败标志: {name}")
            return False

    # 如果仍在登录页面 —— 登录未成功
    if resp.url and ("UserLogin" in resp.url or (
        "login.php" in resp.url and "takelogin" not in resp.url
    )):
        t = re.search(r"<title>([^<]*)</title>", html)
        if t and ("登录" in t.group(1) or "Login" in t.group(1)):
            print(f"  仍在登录页面: {t.group(1)}")
            return False

    # 成功：URL 跳转离开登录相关页面
    login_urls = ["UserLogin", "login.php", "takelogin.php"]
    if resp.url:
        is_login_page = any(lu in resp.url for lu in login_urls)
        if not is_login_page:
            print(f"  已跳转到: {resp.url}")
            return True

    # 页面标题检查
    title_match = re.search(r"<title>([^<]*)</title>", html)
    if title_match:
        title = title_match.group(1)
        if "首页" in title and "登录" not in title:
            print(f"  页面标题: {title}")
            return True

    # Cookie 检查
    required_cookies = ["c_secure_uid", "c_session_token"]
    cookie_names = [c.name for c in session.cookies]
    if all(rc in cookie_names for rc in required_cookies):
        print(f"  检测到认证 cookie: c_secure_uid + c_session_token")
        return True

    # 内容检查
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text()
    user_indicators = ["欢迎", "上次登录", "魔力值", "控制面板", "退出登录"]
    for indicator in user_indicators:
        if indicator in body_text:
            print(f"  检测到用户内容: '{indicator}'")
            return True

    print("  [警告] 无法确定登录状态")
    return None


def login(proxy=None):
    """
    执行登录流程（每次运行登录一次）。

    返回 (session, reason):
        session 不为 None → 登录成功（cookie 已保存到本地文件）
        session 为 None 时 reason ∈ {"fatal", "refused", "failed"}
    """
    print("=" * 60)
    print("  azusa.wiki 自动登录")
    print(f"  账号: {USERNAME}")
    print(f"  最多尝试: {MAX_ATTEMPTS} 次")
    if proxy:
        print(f"  代理: {proxy}")
    print("=" * 60)

    if not USERNAME or not PASSWORD:
        print("[错误] 未配置 AZUSA_USERNAME / AZUSA_PASSWORD (见项目根 .env)")
        return None, "failed"

    session = http.make_session(proxy=proxy)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n--- 第 {attempt} 次尝试 ---")

        csrf_token, imagehash, attempts_left, fatal_error = get_login_page(session)
        if fatal_error:
            print(f"[致命错误] {fatal_error}，停止登录")
            return None, "fatal"
        if not csrf_token or not imagehash:
            print("[跳过] 获取登录页面参数失败")
            time.sleep(2)
            continue

        captcha_text = get_captcha(session, imagehash)
        if not captcha_text:
            print("[跳过] 验证码识别失败")
            time.sleep(1)
            continue

        if len(captcha_text) < 3 or len(captcha_text) > 8:
            print(f"[警告] 验证码长度异常 ({len(captcha_text)}): '{captcha_text}'")

        print("  正在提交登录...")
        try:
            resp = do_login(session, csrf_token, imagehash, captcha_text)
        except Exception as e:
            print(f"[错误] 网络请求失败: {e}")
            time.sleep(2)
            continue

        success = check_login_success(resp, session)

        if success == "fatal":
            print("[致命错误] IP 已被封禁或账号被锁定，停止尝试")
            return None, "fatal"

        if success is True:
            print("\n" + "=" * 60)
            print("  ✅ 登录成功!")
            print("=" * 60)
            cookies.save_netscape(session, COOKIE_FILE)

            print(f"  当前页面: {resp.url}")

            # 验证 cookie 有效性
            print("\n  正在验证登录状态...")
            test_resp = session.get(f"{BASE_URL}/index.php", timeout=30)
            title_match = re.search(r"<title>([^<]*)</title>", test_resp.text)
            if title_match:
                title = title_match.group(1)
                if "登录" not in title:
                    print(f"  ✅ Cookie 有效，页面: {title}")
                else:
                    print(f"  ⚠️  页面标题含'登录': {title}")
            else:
                print("  ⚠️  请手动检查登录状态")

            return session, "ok"

        elif success is False:
            if "密码" in resp.text or "用户" in resp.text:
                print("[致命错误] 用户名或密码错误，请检查账号密码！")
                break
            print(f"  验证码错误，2秒后重试... (剩余 {MAX_ATTEMPTS - attempt} 次)")
            time.sleep(2)
        else:
            print("  3秒后重试...")
            time.sleep(3)

    print("\n" + "=" * 60)
    print("  ❌ 登录失败，已达最大尝试次数")
    print("=" * 60)
    return None, "failed"


# ============================================================
# 搜索模块
# ============================================================

def _parse_torrent_row(tr, base_url):
    """
    解析一个种子 <tr> 行，返回种子信息字典。

    每个种子由两行 <tr> 组成：
    - 第1行：作品类型、标题、副标题、评论数、存活时间、大小、种子/下载/完成数
    - 第2行（可选）：发布者、标签等附加信息
    """
    # 只取行直接子级的 td。注意不能递归：标题格内嵌的 torrentname 表
    # 会把列索引打乱（该站行结构: 类型|标题|评论|时间|大小|做种统计）
    cells = tr.find_all("td", recursive=False)
    if len(cells) < 6:
        return None

    result = {}

    # --- Cell 0: 作品类型 (Category) ---
    cat_img = cells[0].find("img")
    if cat_img:
        result["category"] = cat_img.get("title", "")
        result["category_img_class"] = cat_img.get("class", [""])[0] if cat_img.get("class") else ""

    # --- Cell 1: 标题、副标题、促销类型、下载链接 ---
    title_cell = cells[1]
    inner_table = title_cell.find("table", class_="torrentname")
    if inner_table:
        inner_cells = inner_table.find_all("td")
        content_td = inner_cells[0] if inner_cells else title_cell
        link_td = inner_cells[1] if len(inner_cells) > 1 else None
    else:
        content_td = title_cell
        link_td = None

    # Torrent ID & 详情链接
    detail_link = content_td.find("a", href=re.compile(r"details\.php\?id=\d+"))
    if detail_link:
        href = detail_link.get("href", "")
        tid_match = re.search(r"id=(\d+)", href)
        result["id"] = int(tid_match.group(1)) if tid_match else None
        result["detail_url"] = base_url + "/" + href.replace("&amp;", "&")

        # 标题
        title_b = detail_link.find("b")
        result["title"] = title_b.get_text(strip=True) if title_b else detail_link.get_text(strip=True)
    else:
        result["id"] = None
        result["detail_url"] = None
        result["title"] = ""

    # 热门标记
    hot_font = content_td.find("font", class_="hot")
    result["is_hot"] = hot_font is not None

    # 置顶等级
    sticky_imgs = content_td.find_all("img", class_="sticky")
    result["sticky_level"] = len(sticky_imgs)

    # 促销类型 (Free / 2X / 50% / 30%)
    promo_img = content_td.find("img", class_=re.compile(r"pro_"))
    result["promotion"] = ""
    if promo_img:
        promo_class = " ".join(promo_img.get("class", []))
        if "pro_free" in promo_class:
            result["promotion"] = "免费"
        elif "pro_2x" in promo_class:
            result["promotion"] = "2X"
        elif "pro_50" in promo_class:
            result["promotion"] = "50%"
        elif "pro_30" in promo_class:
            result["promotion"] = "30%"

    # 剩余时间
    time_font = content_td.find("font", string=re.compile(r"剩余时间"))
    if time_font:
        time_span = time_font.find("span")
        if time_span:
            result["remaining_time"] = time_span.get_text(strip=True)
            result["remaining_time_deadline"] = time_span.get("title", "")
        else:
            time_text = time_font.get_text(strip=True)
            result["remaining_time"] = time_text.replace("剩余时间：", "").strip()
            result["remaining_time_deadline"] = ""
    else:
        result["remaining_time"] = ""
        result["remaining_time_deadline"] = ""

    # 副标题：<br/> 后面的文本
    br_tag = content_td.find("br")
    if br_tag:
        subtitle_parts = []
        for sibling in br_tag.next_siblings:
            if isinstance(sibling, str):
                subtitle_parts.append(sibling.strip())
            elif sibling.name == "span":
                subtitle_parts.append(sibling.get_text(strip=True))
            elif sibling.name == "a" or sibling.name == "img":
                break
        result["subtitle"] = " ".join(p for p in subtitle_parts if p)
    else:
        result["subtitle"] = ""

    # 标签 (如: 全存档, 电子版, 自购, 禁转 等)
    tags = []
    if br_tag:
        for sibling in br_tag.next_siblings:
            if hasattr(sibling, "name") and sibling.name == "span":
                tag_text = sibling.get_text(strip=True)
                if tag_text:
                    tags.append(tag_text)
    result["tags"] = tags

    # 下载链接
    if link_td:
        download_a = link_td.find("a", href=re.compile(r"download\.php\?id=\d+"))
        if download_a:
            dl_href = download_a.get("href", "")
            result["download_url"] = base_url + "/" + dl_href.replace("&amp;", "&")

    if "download_url" not in result:
        # 回退：在整行中搜索下载链接
        dl_a = tr.find("a", href=re.compile(r"download\.php\?id=\d+"))
        if dl_a:
            result["download_url"] = base_url + "/" + dl_a.get("href", "").replace("&amp;", "&")
        else:
            # 用种子 ID 构造下载链接
            if result["id"]:
                result["download_url"] = f"{base_url}/download.php?id={result['id']}"
            else:
                result["download_url"] = ""

    # --- Cell 2: 评论数 ---
    comment_a = cells[2].find("a")
    try:
        result["comments"] = int(comment_a.get_text(strip=True)) if comment_a else 0
    except ValueError:
        result["comments"] = 0

    # --- Cell 3: 存活时间 / 上传日期 ---
    time_span = cells[3].find("span")
    if time_span:
        result["upload_time_label"] = time_span.get_text(strip=True).replace("\n", "").replace("\r", "")
        result["upload_time_iso"] = time_span.get("title", "")
        if result["upload_time_iso"]:
            try:
                result["upload_datetime"] = datetime.fromisoformat(result["upload_time_iso"])
            except ValueError:
                result["upload_datetime"] = None
        else:
            result["upload_datetime"] = None
    else:
        result["upload_time_label"] = cells[3].get_text(strip=True)
        result["upload_time_iso"] = ""
        result["upload_datetime"] = None

    # --- Cell 4: 种子大小 ---
    size_text = cells[4].get_text(strip=True)
    result["size_raw"] = size_text
    # 解析数值（如 "373.44\nMB" → 373.44, unit MB）
    size_match = re.match(r"([\d.]+)\s*(\w+)", size_text)
    if size_match:
        result["size_value"] = float(size_match.group(1))
        result["size_unit"] = size_match.group(2)
    else:
        result["size_value"] = None
        result["size_unit"] = ""

    # --- Cell 5: 种子数 / 下载数 / 完成数 ---
    stats_text = cells[5].get_text(strip=True)
    stats_match = re.match(r"(\d+)\s*/\s*(\d+)\s*/\s*(\d+)", stats_text)
    if stats_match:
        result["seeders"] = int(stats_match.group(1))
        result["leechers"] = int(stats_match.group(2))
        result["completed"] = int(stats_match.group(3))
    else:
        result["seeders"] = 0
        result["leechers"] = 0
        result["completed"] = 0

    return result


def search_torrents(session, keyword, page=0, search_area=0, search_mode=0, incldead=0):
    """
    搜索种子

    参数:
        session:    已登录的 requests.Session
        keyword:    搜索关键词
        page:       页码（0 为第一页）
        search_area: 0=标题, 1=简介, 3=发布者, 4=IMDb链接
        search_mode: 0=与, 1=或, 2=准确
        incldead:   0=包括断种, 1=活种, 2=断种

    返回:
        dict {
            "keyword": str,
            "total_results": int,       # 大约总数（网站不一定给精确值）
            "page": int,
            "results_per_page": int,
            "results": [dict, ...],
        }
    """
    params = {
        "search": keyword,
        "search_area": search_area,
        "search_mode": search_mode,
        "incldead": incldead,
    }
    if page > 0:
        params["page"] = page

    resp = session.get(f"{BASE_URL}/torrents.php", params=params, timeout=30)
    html = resp.text

    # 检查是否被重定向到登录页
    if "登录" in html and "torrent" not in html[:500].lower():
        title_match = re.search(r"<title>([^<]*)</title>", html)
        if title_match and "登录" in title_match.group(1):
            raise RuntimeError("Session 未登录，请先执行登录！")

    soup = BeautifulSoup(html, "lxml")

    results = []

    # 只遍历 class="torrents" 列表表格的直接子 <tr>。
    # 注意：不能遍历全页所有 <tr> —— 顶部搜索框/筛选行里也混有
    # download.php / details.php 快捷链接，且整页有嵌套表格包装行。
    torrents_table = soup.find("table", class_="torrents")
    if torrents_table is None:
        raise RuntimeError("未找到种子列表表格（页面结构可能已变化）")
    all_rows = torrents_table.find_all("tr", recursive=False)

    for tr in all_rows:
        # 双重保险：行内需同时含 details.php 与 download.php 链接
        has_download = tr.find("a", href=re.compile(r"download\.php\?id=\d+"))
        has_detail = tr.find("a", href=re.compile(r"details\.php\?id=\d+"))
        if has_download and has_detail:
            torrent = _parse_torrent_row(tr, BASE_URL)
            if torrent and torrent.get("id"):
                results.append(torrent)

    # 尝试提取总数信息（从分页区域）
    total_estimate = len(results)  # fallback
    page_nav = soup.find("p", class_="pager")
    if page_nav:
        # 类似 "1 - 100 | 101 - 200 | ..."
        last_page_text = page_nav.get_text()
        nums = re.findall(r"(\d+)\s*-\s*(\d+)", last_page_text)
        if nums:
            total_estimate = int(nums[-1][1])

    return {
        "keyword": keyword,
        "total_results_estimate": total_estimate,
        "page": page,
        "results_per_page": len(results),
        "results": results,
    }


def print_search_results(search_data, concise=False):
    """格式化输出搜索结果"""
    results = search_data["results"]
    keyword = search_data["keyword"]
    total = search_data["total_results_estimate"]

    print("\n" + "=" * 100)
    print(f"  搜索: \"{keyword}\" — 约 {total} 个结果，当前页显示 {len(results)} 个")
    print("=" * 100)

    if concise:
        # 简洁模式：单行显示
        print(f"\n{'ID':<7} {'类型':<8} {'标题':<45} {'大小':<10} {'种子':>5} {'下载':>5} {'完成':>6}  {'存活时间'}")
        print("-" * 100)
        for t in results:
            sid = str(t.get("id", "?"))
            cat = t.get("category", "")[:6]
            title = t.get("title", "")[:43]
            size = t.get("size_raw", "")
            seeds = t.get("seeders", 0)
            leech = t.get("leechers", 0)
            comp = t.get("completed", 0)
            time_label = t.get("upload_time_label", "")
            print(f"{sid:<7} {cat:<8} {title:<45} {size:<10} {seeds:>5} {leech:>5} {comp:>6}  {time_label}")
    else:
        # 详细模式：多行显示每个种子
        for i, t in enumerate(results, 1):
            print(f"\n{'─' * 100}")
            print(f"  [{i}] {t.get('title', 'N/A')}")

            # 置顶/热门/促销标记
            flags = []
            if t.get("sticky_level", 0) > 0:
                flags.append(f"置顶 Lv.{t['sticky_level']}")
            if t.get("is_hot"):
                flags.append("热门")
            if t.get("promotion"):
                flags.append(t["promotion"])
            if flags:
                print(f"      标记: {', '.join(flags)}")

            # 标签
            if t.get("tags"):
                print(f"      标签: {', '.join(t['tags'])}")

            # 副标题
            if t.get("subtitle"):
                print(f"      副标题: {t['subtitle']}")

            # 基本信息
            print(f"      类型: {t.get('category', 'N/A')}  |  "
                  f"大小: {t.get('size_raw', 'N/A')}  |  "
                  f"种子: {t.get('seeders', 0)}  |  "
                  f"下载中: {t.get('leechers', 0)}  |  "
                  f"已完成: {t.get('completed', 0)}")

            # 时间信息
            time_parts = []
            if t.get("remaining_time"):
                time_parts.append(f"剩余: {t['remaining_time']}")
            if t.get("upload_time_label"):
                time_parts.append(f"上传于: {t['upload_time_label']}")
            if t.get("upload_time_iso"):
                time_parts.append(f"({t['upload_time_iso']})")
            if time_parts:
                print(f"      时间: {'  |  '.join(time_parts)}")

            # 评论
            print(f"      评论: {t.get('comments', 0)}")

            # 链接
            print(f"      详情: {t.get('detail_url', 'N/A')}")
            print(f"      下载: {t.get('download_url', 'N/A')}")

    print(f"\n{'─' * 100}")
    print(f"共 {len(results)} 条记录")


# ============================================================
# 命令行入口
# ============================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="azusa.wiki 自动登录 & 种子搜索工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --search "汉化"              # 每次运行登录一次，然后搜索
  %(prog)s --search "东立" --page 1     # 搜索第2页
  %(prog)s --search "完结" --concise    # 简洁输出
  %(prog)s --search "汉化" --proxy http://127.0.0.1:7890   # 走 HTTP 代理
  %(prog)s --search "汉化" --json-only  # 仅输出JSON
  %(prog)s --search "汉化" --force-login  # 登录被拒时不用本地cookie回退
        """,
    )
    parser.add_argument("--search", "-s", type=str, default=None,
                        help="搜索关键词")
    parser.add_argument("--page", "-p", type=int, default=0,
                        help="页码 (默认: 0 = 第1页)")
    parser.add_argument("--search-area", "-a", type=int, default=0,
                        choices=[0, 1, 3, 4],
                        help="搜索范围: 0=标题, 1=简介, 3=发布者, 4=IMDb")
    parser.add_argument("--search-mode", "-m", type=int, default=0,
                        choices=[0, 1, 2],
                        help="匹配模式: 0=与, 1=或, 2=准确")
    parser.add_argument("--incldead", "-d", type=int, default=0,
                        choices=[0, 1, 2],
                        help="种子状态: 0=包括断种, 1=活种, 2=断种")
    parser.add_argument("--concise", "-c", action="store_true",
                        help="简洁输出模式（单行一条）")
    parser.add_argument("--force-login", "-f", action="store_true",
                        help="登录被拒/失败时不回退使用本地 cookie")
    parser.add_argument("--json-only", "-j", action="store_true",
                        help="只输出 JSON，不打印表格")
    parser.add_argument("--proxy", type=str, default=env.get("AZUSA_PROXY") or None,
                        help="HTTP 代理，如 http://127.0.0.1:7890"
                             "（默认读取 .env 的 AZUSA_PROXY）")
    return parser.parse_args()


def ensure_ready_session(args):
    """
    获取可用的登录 session。流程：

      1. 先加载本地 cookie（供后续回退使用）
      2. 每次运行都登录一次 —— 登录前在登录页检测剩余尝试次数，
         剩余 ≤2 次则拒绝登录并警告
      3. 登录成功 → cookie 已保存到本地（azusa_cookies.txt）
      4. 登录被拒/失败 → 优先利用本地 cookie，验证仍有效则继续

    返回已登录 session；无法取得有效状态时返回 None。
    """
    proxy = args.proxy
    session = http.make_session(proxy=proxy)

    # 1. 预加载本地 cookie
    if COOKIE_FILE.exists():
        cookies.load_netscape(session, COOKIE_FILE)

    # 2. 每次运行登录一次
    if proxy:
        print(f"[代理] 使用 HTTP 代理: {proxy}")
    login_session, reason = login(proxy=proxy)

    if login_session is not None:
        # 3. 登录成功，把 cookie 复制回主 session（login() 内已保存本地）
        for cookie in login_session.cookies:
            session.cookies.set(
                cookie.name, cookie.value,
                domain=cookie.domain, path=cookie.path,
            )
        return session

    # 4. 登录未执行或失败 → 优先利用本地 cookie
    if reason == "fatal":
        print("\n[退出] 检测到 IP 封禁 / 账号锁定 / 尝试次数耗尽。")
        print("       服务器会在 cookie 校验前拒绝所有请求，本地 cookie 无法绕过。")
        print("       建议: 等待封禁解除，或用代理/其他 IP 运行（--proxy）")
        return None

    if args.force_login:
        print("\n[退出] 已指定 --force-login，不使用本地 cookie 回退。")
        return None

    print("\n[回退] 本次未登录，尝试使用本地保存的 cookie ...")
    if http.is_logged_in(session, f"{BASE_URL}/index.php",
                         fail_keywords=("我们怀疑你在欺骗系统", "禁用了你的IP",
                                        "Login 锁定", "最大错误尝试次数"),
                         cookie_names=("c_secure_uid",),
                         title_excludes=("登录",)):
        print("  ⚠️  已用本地 cookie 继续（本次未登录，注意剩余次数）")
        return session

    print("[退出] 本地 cookie 也已失效。")
    print("       建议: 等待封禁解除，或用代理/其他 IP 运行（--proxy）")
    return None


def main():
    args = parse_args()

    # --- 登录：每次运行登录一次，剩余次数≤2 拒绝并回退本地 cookie ---
    session = ensure_ready_session(args)
    if session is None:
        print("无法获取有效登录状态，退出。")
        sys.exit(1)

    # --- 搜索 ---
    if args.search:
        print(f"🔍 正在搜索: \"{args.search}\"...")
        try:
            data = search_torrents(
                session,
                keyword=args.search,
                page=args.page,
                search_area=args.search_area,
                search_mode=args.search_mode,
                incldead=args.incldead,
            )
        except RuntimeError as e:
            print(f"\n[错误] {e}")
            sys.exit(1)

        if args.json_only:
            print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        else:
            print_search_results(data, concise=args.concise)
    else:
        print("提示: 使用 --search '关键词' 来搜索种子")
        print("      使用 --help 查看更多选项")


if __name__ == "__main__":
    main()
