#!/usr/bin/env python3
"""u2.dmhy.org — 签到 & 种子搜索

Usage:
  python dmhy.py checkin              # 每日签到（随机选作品，≥5字留言）
  python dmhy.py search <keyword>     # 搜索种子
  python dmhy.py search <keyword> -n 20  # 最多返回20条
  python dmhy.py -v search <keyword>  # 详细输出

依赖: 复用 login.py 的 cookies.pkl，需先运行过 login.py 成功登录。
"""

import argparse
import json
import logging
import os
import random
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, quote

import requests
from bs4 import BeautifulSoup

# 确保能 import 项目根的 common 包
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SITE_DIR, "..", ".."))
for _p in (_SITE_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import constants, cookies, env, http

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://u2.dmhy.org"
# 原为 CWD 相对路径 "cookies.pkl"，合并后改为脚本目录绝对路径
COOKIE_FILE = Path(_SITE_DIR) / "cookies.pkl"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_parser():
    p = argparse.ArgumentParser(description="u2.dmhy.org 签到 & 搜索")
    p.add_argument("--verbose", "-v", action="store_true", help="详细日志")
    p.add_argument("--timeout", type=int, default=30, help="HTTP 超时(秒)")
    p.add_argument("--proxy", default=env.get_proxy(), help="代理地址")
    sub = p.add_subparsers(dest="command")

    c = sub.add_parser("checkin", help="每日签到")
    c.add_argument("-m", "--message", default="一切随缘~", help="签到留言（≥5字符）")

    s = sub.add_parser("search", help="搜索种子")
    s.add_argument("keyword", help="搜索关键字")
    s.add_argument("-n", "--limit", type=int, default=50, help="最多返回条数 (默认50)")
    return p


# ---------------------------------------------------------------------------
# Session helpers (见 common 包)
# ---------------------------------------------------------------------------
def _make_session(proxy: str = "") -> requests.Session:
    """dmhy 专用 session: 保留原 UA 与精简 Accept。"""
    return http.make_session(proxy, ua=constants.UA_CHROME_WIN,
                             extra_headers={"Accept": "text/html,application/xhtml+xml"})


def _load_session(proxy: str = "") -> Optional[requests.Session]:
    """从 cookies.pkl 恢复会话,失败返回 None。

    原实现用 _make_session(proxy) 装配 UA/代理后再套 cookies,
    load_pickle 返回裸 session,这里补回 header 与代理保持一致。
    """
    s = cookies.load_pickle(COOKIE_FILE)
    if s is None:
        return None
    s.headers.update(_make_session(proxy).headers)
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def _ensure_logged_in(session: requests.Session, timeout: int = 30) -> bool:
    """检查 session 登录态 (页面含 logout/usercp 视为已登录)。"""
    return http.is_logged_in(session, f"{BASE_URL}/index.php",
                             success_keywords=("logout", "usercp"),
                             timeout=timeout)


# ---------------------------------------------------------------------------
# Check-in
# ---------------------------------------------------------------------------
def checkin(session: requests.Session, message: str = "一切随缘~",
            timeout: int = 30, log=None) -> dict:
    """
    每日签到。随机选一个 CAPTCHA 作品名称提交。

    Returns: {"success": bool, "message": str, "ucoin": int|None, ...}
    """
    if log is None:
        log = logging.getLogger(__name__)

    if len(message) < 5:
        message = message.ljust(5, "~")

    # 1. GET showup.php → parse form
    log.info("Fetching check-in page...")
    try:
        r = session.get(f"{BASE_URL}/showup.php", timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        return {"success": False, "message": f"Failed to fetch check-in page: {e}"}

    soup = BeautifulSoup(r.text, "lxml")

    # Find the check-in form
    form = None
    for f in soup.find_all("form"):
        action = f.get("action", "")
        if "showup.php" in action and "action=show" in action:
            form = f
            break

    if not form:
        body = soup.get_text()
        if any(kw in body for kw in ["感谢，今天已签到", "已经签到", "已签到"]):
            return {"success": True, "message": "Already checked in today", "already": True}
        return {"success": False, "message": "Could not find check-in form on page"}

    # 2. Extract hidden fields
    payload = {}
    for inp in form.find_all("input", type="hidden"):
        payload[inp.get("name", "")] = inp.get("value", "")

    req_val = payload.get("req", "")
    hash_val = payload.get("hash", "")
    if not req_val or not hash_val:
        return {"success": False, "message": "Missing required hidden fields (req/hash)"}

    # 3. Collect CAPTCHA work-name buttons
    captcha_buttons = []
    for inp in form.find_all("input", type="submit"):
        name = inp.get("name", "")
        if name.startswith("captcha_"):
            captcha_buttons.append({"name": name, "value": inp.get("value", "")})

    if not captcha_buttons:
        return {"success": False, "message": "No CAPTCHA work-name buttons found"}

    log.info("Found %d work-name options", len(captcha_buttons))

    # 4. Random pick
    chosen = random.choice(captcha_buttons)
    log.info("Randomly selected: %s", chosen["value"][:80])

    payload["message"] = message
    payload[chosen["name"]] = chosen["value"]

    # 5. POST
    submit_url = urljoin(BASE_URL, form.get("action", "showup.php?action=show"))
    session.headers.update({
        "Referer": f"{BASE_URL}/showup.php",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    log.info("Submitting check-in...")
    try:
        r2 = session.post(submit_url, data=payload, timeout=timeout)
    except requests.RequestException as e:
        return {"success": False, "message": f"Check-in request failed: {e}"}

    resp_text = r2.text
    log.debug("POST response (first 300): %s", resp_text[:300])

    # 6. Parse response

    # JSON?
    try:
        data = json.loads(resp_text)
        if data.get("status") == "success" or data.get("success"):
            return {"success": True,
                    "message": data.get("message", "Check-in successful"),
                    "ucoin": data.get("ucoin") or data.get("bonus"), "correct": True}
        return {"success": False,
                "message": data.get("message", "Check-in failed"),
                "ucoin": data.get("ucoin", 0)}
    except json.JSONDecodeError:
        pass

    # JS redirect → follow it
    m_redirect = re.search(r"window\.location\.href\s*=\s*'([^']+)'", resp_text)
    if m_redirect:
        redirect_url = urljoin(BASE_URL, m_redirect.group(1))
        log.info("Following JS redirect → %s", redirect_url)
        try:
            r3 = session.get(redirect_url, timeout=timeout)
            resp_text = r3.text
        except requests.RequestException:
            pass

    soup2 = BeautifulSoup(resp_text, "lxml")
    body = soup2.get_text()

    # Check if our message appears in recent records (means submitted OK)
    if message in body:
        ucoin = None
        idx = body.find(message)
        nearby = body[max(0, idx - 200):idx + 200]
        m = re.search(r"奖励UCoin[：:]\s*(\d+)", nearby)
        if m:
            ucoin = int(m.group(1))
        if "回答正确" in nearby:
            return {"success": True,
                    "message": "Check-in successful — answer correct!",
                    "ucoin": ucoin, "correct": True}
        elif "回答错误" in nearby:
            return {"success": True,
                    "message": "Check-in submitted — answer wrong (still counts)",
                    "ucoin": ucoin or 1, "correct": False}
        return {"success": True, "message": "Check-in submitted", "ucoin": ucoin}

    if "回答正确" in body:
        m = re.search(r"奖励UCoin[：:]\s*(\d+)", body)
        return {"success": True,
                "message": "Check-in successful — answer correct!",
                "ucoin": int(m.group(1)) if m else None, "correct": True}
    elif "回答错误" in body:
        m = re.search(r"奖励UCoin[：:]\s*(\d+)", body)
        return {"success": True,
                "message": "Check-in submitted — answer wrong (still counts)",
                "ucoin": int(m.group(1)) if m else 1, "correct": False}
    elif any(kw in body for kw in ["感谢，今天已签到", "已经签到", "已签到"]):
        return {"success": True, "message": "Already checked in today", "already": True}
    elif "验证问题有效期" in body:
        return {"success": False,
                "message": "CAPTCHA expired, retry (session still valid)"}

    snippet = body[:300].replace("\n", " ").strip()
    return {"success": False, "message": f"Unknown response: {snippet[:200]}"}


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def search(session: requests.Session, keyword: str, limit: int = 50,
           timeout: int = 30, log=None) -> dict:
    """
    搜索种子。

    Returns: {"success": bool, "results": [...], "total": int}

    每条结果:
        category    — 作品类型 (BDMV, BDRip, DVDISO, ...)
        title       — 标题
        subtitle    — 副标题 / 促销说明
        size        — 种子大小
        survival    — 生存时间
        seeders     — 种子数
        leechers    — 下载中
        completed   — 已完成下载
        details_url — 详情页链接
        download_url— 种子下载链接
        rating      — 评分
        comments    — 评论数
    """
    if log is None:
        log = logging.getLogger(__name__)

    url = f"{BASE_URL}/torrents.php?search={quote(keyword)}&notnewword=1"
    log.info("Searching: %s", url)

    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        return {"success": False, "results": [], "total": 0,
                "message": f"Search request failed: {e}"}

    soup = BeautifulSoup(r.text, "lxml")
    torrent_table = soup.find("table", class_="torrents")
    if not torrent_table:
        body = soup.get_text()
        if any(kw in body for kw in ["没有找到", "无结果", "nothing found"]):
            return {"success": True, "results": [], "total": 0,
                    "message": "No results found"}
        return {"success": False, "results": [], "total": 0,
                "message": "Could not find torrent table on page"}

    results = []
    for row in torrent_table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue

        # Torrent data rows have "rowfollow" class on first cell (category)
        first_cls = " ".join(cells[0].get("class", []))
        if "rowfollow" not in first_cls:
            continue

        if len(cells) < 12:
            continue

        try:
            category = cells[0].get_text(strip=True)

            title_link = cells[1].find("a")
            title = title_link.get_text(strip=True) if title_link else ""
            details_href = title_link.get("href", "") if title_link else ""

            subtitle = cells[4].get_text(strip=True) if len(cells) > 4 else ""

            rating_text = cells[5].get_text(strip=True) if len(cells) > 5 else ""
            try:
                rating = float(rating_text) if rating_text else None
            except ValueError:
                rating = None

            survival = cells[7].get_text(strip=True) if len(cells) > 7 else ""
            size = cells[8].get_text(strip=True) if len(cells) > 8 else ""

            def _int(text):
                try:
                    return int(text.strip())
                except (ValueError, AttributeError):
                    return 0

            seeders = _int(cells[9].get_text(strip=True)) if len(cells) > 9 else 0
            leechers = _int(cells[10].get_text(strip=True)) if len(cells) > 10 else 0
            completed = _int(cells[11].get_text(strip=True)) if len(cells) > 11 else 0
            comments = _int(cells[6].get_text(strip=True)) if len(cells) > 6 else 0

            dl_link = None
            if len(cells) > 3:
                dl_link = cells[3].find("a", href=lambda h: h and "download.php" in h)
            download_href = dl_link.get("href", "") if dl_link else ""

            results.append({
                "category":    category,
                "title":       title,
                "subtitle":    subtitle,
                "size":        size,
                "survival":    survival,
                "seeders":     seeders,
                "leechers":    leechers,
                "completed":   completed,
                "details_url": urljoin(BASE_URL, details_href) if details_href else "",
                "download_url": urljoin(BASE_URL, download_href) if download_href else "",
                "rating":      rating,
                "comments":    comments,
            })

            if len(results) >= limit:
                break
        except Exception as e:
            log.warning("Failed to parse a torrent row: %s", e)
            continue

    log.info("Parsed %d torrent results", len(results))
    return {"success": True, "results": results, "total": len(results)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    env.load_env()
    parser = _build_parser()
    config = parser.parse_args()

    if not config.command:
        parser.print_help()
        return 1

    level = logging.DEBUG if config.verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    log = logging.getLogger("dmhy")

    session = _load_session(config.proxy)
    if not session:
        print(json.dumps({"success": False,
                          "message": "No cookies.pkl found. Run login.py first."}))
        return 1

    if not _ensure_logged_in(session, config.timeout):
        print(json.dumps({"success": False,
                          "message": "Session expired. Re-run login.py."}))
        return 1

    log.info("Session valid.")

    if config.command == "checkin":
        result = checkin(session, message=config.message,
                         timeout=config.timeout, log=log)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    elif config.command == "search":
        result = search(session, config.keyword, limit=config.limit,
                        timeout=config.timeout, log=log)
        if config.verbose:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            out = {"success": result["success"], "total": result["total"],
                   "results": result["results"]}
            if "message" in result:
                out["message"] = result["message"]
            print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if result["success"] else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
