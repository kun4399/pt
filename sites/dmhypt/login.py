#!/usr/bin/env python3
"""u2.dmhy.org login — OCR 自动登录(验证码 ddddocr+tesseract 双引擎一致)。

流程:
  1. 检查已保存的 cookies.pkl(cookie-first, 有效则秒过)
  2. 无效则 OCR 模式: 下载验证码直到两引擎识别一致, 提交一次
  3. 登录成功 → 保存 cookies.pkl(统一入口/签到/搜索直接复用)

四站统一手动 cookie 方式: 文件放 data/cookies/<站点>/ 或油猴脚本一键发送
(见根 README), 与登录脚本无关。

Safety: 登录页剩余次数 ≤ ATTEMPTS_WARN(.env, 默认 2)时拒绝登录(IP 封禁风险)。

Usage:
  python login.py                  # cookie 有效则跳过, 否则 OCR 登录
  python login.py -v               # verbose
"""

import argparse
import io
import json
import logging
import os
import random
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 确保能 import 项目根的 common 包
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SITE_DIR, "..", ".."))
for _p in (_SITE_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import config, constants, cookies, env, http, sites

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_URL = "https://u2.dmhy.org"
COOKIE_FILE = sites.cookie_path("dmhy") or Path(_SITE_DIR) / "cookies.pkl"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class Config:
    def __init__(self):
        env.load_env()
        p = argparse.ArgumentParser(description="u2.dmhy.org OCR 自动登录")
        p.add_argument("--username", "-u", default=os.getenv("DMHY_USERNAME", ""))
        p.add_argument("--password", "-p", default=os.getenv("DMHY_PASSWORD", ""))
        p.add_argument("--proxy", default=env.get_proxy())
        p.add_argument("--verbose", "-v", action="store_true")
        p.add_argument("--timeout", type=int, default=config.get_int("HTTP_TIMEOUT", 30))
        args = p.parse_args()

        self.username = args.username
        self.password = args.password
        self.proxy = args.proxy
        self.verbose = args.verbose
        self.timeout = args.timeout

        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s",
                            datefmt="%H:%M:%S")

log = logging.getLogger("dmhy")

# ---------------------------------------------------------------------------
# Helpers (session / cookie / 登录态检查见 common 包)
# ---------------------------------------------------------------------------
def make_session(proxy: str = "") -> requests.Session:
    """dmhy 专用 session: 保留原 UA 与精简 Accept。"""
    return http.make_session(proxy, ua=constants.UA_CHROME_WIN,
                             extra_headers={"Accept": "text/html,application/xhtml+xml"})


def is_logged_in(session: requests.Session, config: Config) -> bool:
    """检查 session 登录态 (页面含 logout/usercp 视为已登录)。"""
    return http.is_logged_in(session, f"{BASE_URL}/",
                             success_keywords=("logout", "usercp"),
                             timeout=config.timeout)


def get_attempts(soup: BeautifulSoup) -> tuple[int, int]:
    """Return (remaining, total) attempts from login page."""
    left = soup.find("span", class_="attempt-left-counter")
    full = soup.find("span", class_="attempt-full-counter")
    if left and full:
        try:
            return int(left.text.strip()), int(full.text.strip())
        except ValueError:
            pass
    return 20, 20  # default if not found

def parse_form(soup: BeautifulSoup) -> tuple[str, dict, str, str]:
    """Parse login form. Returns (action_url, hidden_fields, username_field, password_field)."""
    form = soup.find("form", id="form-login")
    if not form:
        form = soup.find("form", action=lambda a: a and "takelogin" in a)
    if not form:
        for f in soup.find_all("form"):
            if f.find("input", type="password"):
                form = f
                break
    if not form:
        return "", {}, "username", "password"

    action = urljoin(BASE_URL, form.get("action", "takelogin.php"))
    hidden = {}
    user_field = "username"
    pass_field = "password"
    for inp in form.find_all("input"):
        name = inp.get("name", "")
        if inp.get("type") == "hidden":
            hidden[name] = inp.get("value", "")
        elif inp.get("type") == "password":
            pass_field = name

    return action, hidden, user_field, pass_field

# ---------------------------------------------------------------------------
# OCR helpers (optional, imported on demand)
# ---------------------------------------------------------------------------
_OCR_AVAILABLE = None

def _ocr_available() -> bool:
    global _OCR_AVAILABLE
    if _OCR_AVAILABLE is None:
        try:
            import ddddocr
            import pytesseract
            from PIL import Image
            ddddocr.DdddOcr(show_ad=False)  # test init
            _OCR_AVAILABLE = True
        except Exception:
            _OCR_AVAILABLE = False
    return _OCR_AVAILABLE

def _ocr_both(img_data: bytes) -> tuple[str, str]:
    """Run ddddocr and tesseract on image, return (dddd_result, tess_result)."""
    import ddddocr
    import pytesseract
    from PIL import Image

    WHITELIST = "ABCDEFGHJKLMNPRSTUVWXYZabcdefghjkmnprstuvwxyz23456789"

    img = Image.open(io.BytesIO(img_data))
    gray = img.convert("L")

    # ddddocr — try thresholds
    ocr = ddddocr.DdddOcr(show_ad=False)
    dddd_best = ""
    for thresh in (106, 107, 108, 109, 110):
        bw = gray.point(lambda x, t=thresh: 255 if x > t else 0)
        buf = io.BytesIO(); bw.save(buf, "PNG")
        r = ocr.classification(buf.getvalue()).strip()
        if len(r) == 4:
            dddd_best = r
            break
        if len(r) > len(dddd_best):
            dddd_best = r

    # tesseract
    bw = gray.point(lambda x: 255 if x > 106 else 0)
    big = bw.resize((bw.width * 3, bw.height * 3), Image.LANCZOS)
    cfg = f"--psm 7 -c tessedit_char_whitelist={WHITELIST}"
    try:
        tess_best = pytesseract.image_to_string(big, config=cfg).strip()
        tess_best = "".join(c for c in tess_best if c.isalnum())
    except Exception:
        tess_best = ""

    return dddd_best, tess_best

# ---------------------------------------------------------------------------
# OCR login
# ---------------------------------------------------------------------------
def ocr_login(session: requests.Session, config: Config,
              action: str, hidden: dict, username_field: str, password_field: str) -> Optional[str]:
    """Download CAPTCHAs until ddddocr+tesseract agree, then submit once.
    Returns nexusphp_u2 cookie on success, None on failure.
    """
    log.info("OCR mode: searching for agreed CAPTCHA (max 100 downloads, 0 login attempts until match)...")

    for i in range(100):
        cap_url = urljoin(BASE_URL, f"captcha.php?sid={random.random()}")
        r = session.get(cap_url, timeout=config.timeout)
        img_data = r.content

        d, t = _ocr_both(img_data)
        if len(d) != 4 or len(t) != 4 or d.lower() != t.lower():
            continue

        log.info("OCR agreement after %d downloads: dddd=%r tess=%r", i + 1, d, t)

        # Submit ONCE
        payload = dict(hidden)
        payload[username_field] = config.username
        payload[password_field] = config.password
        payload["captcha"] = d

        session.headers.update({
            "Referer": f"{BASE_URL}/takelogin.php",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        })

        r = session.post(action, data=payload, timeout=config.timeout)
        if config.verbose:
            log.debug("Response: %s", r.text[:500])

        try:
            data = json.loads(r.text)
            if data.get("status") == "redirect":
                cookie = session.cookies.get("nexusphp_u2", "")
                if cookie:
                    log.info("OCR login successful!")
                    cookies.save_pickle(session, COOKIE_FILE)
                    return cookie
            log.warning("OCR login failed on agreed code: %s", data.get("message", ""))
        except json.JSONDecodeError:
            log.warning("OCR login: unexpected response")

        return None  # agreed code failed, don't retry

    log.warning("No OCR agreement after 100 CAPTCHAs")
    return None

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    c = Config()

    # Route 1: Check for saved session (cookie-first)
    s = cookies.load_pickle(COOKIE_FILE)
    if s:
        if c.proxy:
            s.proxies = {"http": c.proxy, "https": c.proxy}
        if is_logged_in(s, c):
            print(json.dumps({"success": True, "message": "Session valid (cached)."}))
            return 0
        log.info("Cached session expired, need to re-login.")

    # Need credentials for login
    if not c.username or not c.password:
        log.error("Username/password required. Set DMHY_USERNAME/DMHY_PASSWORD in .env or -u/-p.")
        return 1

    # Create fresh session for login
    session = make_session(c.proxy)

    # Fetch login page
    log.info("Fetching login page...")
    try:
        r = session.get(f"{BASE_URL}/takelogin.php", timeout=c.timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Failed to reach login page: %s", e)
        return 1

    soup = BeautifulSoup(r.text, "lxml")

    # Safety: check remaining attempts (统一阈值 .env ATTEMPTS_WARN, 默认 2)
    remaining, total = get_attempts(soup)
    warn = config.get_int("ATTEMPTS_WARN", 2)
    log.info("Login attempts remaining: %d/%d", remaining, total)
    if remaining <= warn:
        log.error(
            "Only %d attempt(s) remaining (out of %d)! "
            "Refusing to login to avoid IP ban. "
            "Wait for the counter to reset, or place a valid cookie file instead.",
            remaining, total,
        )
        print(json.dumps({
            "success": False,
            "message": f"Only {remaining}/{total} attempts left — refusing to risk IP ban.",
        }))
        return 1

    # Parse form
    action, hidden, user_field, pass_field = parse_form(soup)
    if not action:
        log.error("Could not find login form")
        return 1

    # OCR login (双引擎一致才提交, 单次尝试)
    if not _ocr_available():
        log.error("OCR 依赖不可用 (ddddocr/pytesseract/PIL), 请先安装或手动放置 cookie 文件")
        return 1

    cookie = ocr_login(session, c, action, hidden, user_field, pass_field)
    if cookie:
        print(json.dumps({"success": True, "message": "OCR login successful, cookie saved."}))
        return 0

    print(json.dumps({"success": False, "message": "OCR login failed."}))
    return 1

if __name__ == "__main__":
    sys.exit(main())
