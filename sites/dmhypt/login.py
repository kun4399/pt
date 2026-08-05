#!/usr/bin/env python3
"""u2.dmhy.org login — three modes, auto-selected:

1. Cookie mode (fastest):
   Set DMHY_COOKIE in .env or pass --cookie VALUE. Saves to cookies.pkl.

2. OCR mode (hands-free):
   Downloads CAPTCHAs until ddddocr+tesseract agree, submits once.

3. Manual CAPTCHA mode (fallback):
   Serves CAPTCHA image via HTTP (frp-friendly), you type the code.

Safety: refuses login when ≤ 2 attempts remain (IP ban risk).

Usage:
  python login.py                  # auto: cookie → ocr → manual
  python login.py --cookie VALUE   # inject cookie
  python login.py --manual         # force manual mode
  python login.py -v               # verbose
"""

import argparse
import base64
import hashlib
import io
import json
import logging
import os
import random
import sys
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
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
# 原为 CWD 相对路径 "cookies.pkl"，合并后改为脚本目录绝对路径
COOKIE_FILE = sites.cookie_path("dmhy") or Path(_SITE_DIR) / "cookies.pkl"
CAPTCHA_PORT = config.get_int("DMHY_CAPTCHA_PORT", 8765)
FRP_PUBLIC_IP = config.get_str("FRP_PUBLIC_IP", "39.101.137.195")
MIN_ATTEMPTS = config.get_int("DMHY_MIN_ATTEMPTS", 3)  # refuse login if ≤ this many remaining

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class Config:
    def __init__(self):
        env.load_env()
        p = argparse.ArgumentParser(description="u2.dmhy.org login")
        p.add_argument("--username", "-u", default=os.getenv("DMHY_USERNAME", ""))
        p.add_argument("--password", "-p", default=os.getenv("DMHY_PASSWORD", ""))
        p.add_argument("--cookie", default=os.getenv("DMHY_COOKIE", ""))
        p.add_argument("--proxy", default=env.get_proxy())
        p.add_argument("--manual", action="store_true", help="Force manual CAPTCHA mode")
        p.add_argument("--verbose", "-v", action="store_true")
        p.add_argument("--timeout", type=int, default=30)
        args = p.parse_args()

        self.username = args.username
        self.password = args.password
        self.cookie = args.cookie
        self.proxy = args.proxy
        self.force_manual = args.manual
        self.verbose = args.verbose
        self.timeout = args.timeout

        level = logging.DEBUG if self.verbose else logging.INFO
        logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")

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
# OCR mode
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
                    env.write_env_value("DMHY_COOKIE", cookie)
                    return cookie
            log.warning("OCR login failed on agreed code: %s", data.get("message", ""))
        except json.JSONDecodeError:
            log.warning("OCR login: unexpected response")

        return None  # agreed code failed, don't retry

    log.warning("No OCR agreement after 100 CAPTCHAs")
    return None

# ---------------------------------------------------------------------------
# Manual CAPTCHA login
# ---------------------------------------------------------------------------
def manual_login(session: requests.Session, config: Config,
                 action: str, hidden: dict, username_field: str, password_field: str) -> Optional[str]:
    """Download CAPTCHA, serve via HTTP, user enters code. One attempt."""
    cap_url = urljoin(BASE_URL, f"captcha.php?sid={random.random()}")
    log.info("Downloading CAPTCHA...")
    r = session.get(cap_url, timeout=config.timeout)
    img_data = r.content

    # Save and serve
    cap_dir = Path(tempfile.gettempdir()) / "dmhy_captcha"
    cap_dir.mkdir(exist_ok=True)
    (cap_dir / "captcha.png").write_bytes(img_data)
    b64 = base64.b64encode(img_data).decode()
    (cap_dir / "captcha.html").write_text(
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>DMHY CAPTCHA</title>'
        '<style>body{display:flex;justify-content:center;align-items:center;'
        'min-height:100vh;background:#1a1a2e;margin:0}'
        'img{border:3px solid #e94560;border-radius:8px;max-width:90vw}'
        '</style></head><body>'
        f'<img src="data:image/png;base64,{b64}" alt="CAPTCHA">'
        '</body></html>')

    class NoCache(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            super().end_headers()

    old_cwd = os.getcwd()
    os.chdir(str(cap_dir))
    server = HTTPServer(("0.0.0.0", CAPTCHA_PORT), NoCache)
    server.allow_reuse_address = True
    threading.Thread(target=server.serve_forever, daemon=True).start()

    img_hash = hashlib.md5(img_data).hexdigest()[:8]
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  CAPTCHA  (hash: {img_hash})", file=sys.stderr)
    print(f"  Open:    http://{FRP_PUBLIC_IP}:{CAPTCHA_PORT}/captcha.html", file=sys.stderr)
    print(f"  or:      http://{FRP_PUBLIC_IP}:{CAPTCHA_PORT}/captcha.png", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)

    try:
        code = input("  Enter 4-char code: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return None
    finally:
        server.shutdown()
        os.chdir(old_cwd)

    if not code:
        log.error("No CAPTCHA code entered")
        return None

    # Submit
    payload = dict(hidden)
    payload[username_field] = config.username
    payload[password_field] = config.password
    payload["captcha"] = code

    session.headers.update({
        "Referer": f"{BASE_URL}/takelogin.php",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded",
    })

    log.info("Submitting login...")
    if config.verbose:
        log.debug("POST payload: %s", {k: v for k, v in payload.items() if "pass" not in k.lower()})

    r = session.post(action, data=payload, timeout=config.timeout)
    if config.verbose:
        log.debug("Response: %s", r.text[:500])

    try:
        data = json.loads(r.text)
        if data.get("status") == "redirect":
            cookie = session.cookies.get("nexusphp_u2", "")
            if cookie:
                log.info("Login successful!")
                cookies.save_pickle(session, COOKIE_FILE)
                env.write_env_value("DMHY_COOKIE", cookie)
                return cookie
            log.error("Login redirected but no cookie received")
        else:
            log.error("Login failed: %s", data.get("message", r.text))
    except json.JSONDecodeError:
        if "logout" in r.text.lower():
            cookie = session.cookies.get("nexusphp_u2", "")
            if cookie:
                cookies.save_pickle(session, COOKIE_FILE)
                env.write_env_value("DMHY_COOKIE", cookie)
                return cookie
        log.error("Login failed: unexpected response")
    return None

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    config = Config()

    # Route 1: User provided a cookie → validate and save
    if config.cookie and not config.force_manual:
        log.info("Testing provided cookie...")
        s = make_session(config.proxy)
        s.cookies.set("nexusphp_u2", config.cookie, domain="u2.dmhy.org", path="/")
        if is_logged_in(s, config):
            cookies.save_pickle(s, COOKIE_FILE)
            env.write_env_value("DMHY_COOKIE", config.cookie)
            print(json.dumps({"success": True, "message": "Cookie is valid, saved."}))
            return 0
        else:
            log.error("Provided cookie is not valid for u2.dmhy.org")
            return 1

    # Route 2: Check for saved session
    if not config.force_manual:
        s = cookies.load_pickle(COOKIE_FILE)
        if s:
            if config.proxy:
                s.proxies = {"http": config.proxy, "https": config.proxy}
            if is_logged_in(s, config):
                print(json.dumps({"success": True, "message": "Session valid (cached)."}))
                return 0
            log.info("Cached session expired, need to re-login.")

    # Need credentials for login
    if not config.username or not config.password:
        log.error("Username/password required. Set DMHY_USERNAME/DMHY_PASSWORD in .env or -u/-p.")
        return 1

    # Create fresh session for login
    session = make_session(config.proxy)

    # Fetch login page
    log.info("Fetching login page...")
    try:
        r = session.get(f"{BASE_URL}/takelogin.php", timeout=config.timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("Failed to reach login page: %s", e)
        return 1

    soup = BeautifulSoup(r.text, "lxml")

    # Safety: check remaining attempts
    remaining, total = get_attempts(soup)
    log.info("Login attempts remaining: %d/%d", remaining, total)
    if remaining < MIN_ATTEMPTS:
        log.error(
            "Only %d attempt(s) remaining (out of %d)! "
            "Refusing to login to avoid IP ban. "
            "Wait for the counter to reset, or use cookie mode instead.",
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

    # Try OCR mode first (unless --manual), fall back to manual
    if not config.force_manual and _ocr_available():
        cookie = ocr_login(session, config, action, hidden, user_field, pass_field)
        if cookie:
            print(json.dumps({"success": True, "message": "OCR login successful, cookie saved."}))
            return 0
        log.info("OCR mode failed, falling back to manual...")

    # Manual mode
    cookie = manual_login(session, config, action, hidden, user_field, pass_field)
    if cookie:
        print(json.dumps({"success": True, "message": "Login successful, cookie saved."}))
        return 0

    print(json.dumps({"success": False, "message": "Login failed."}))
    return 1

if __name__ == "__main__":
    sys.exit(main())
