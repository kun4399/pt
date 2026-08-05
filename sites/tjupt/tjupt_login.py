#!/usr/bin/env python3
"""
TJUPT (https://tjupt.org) 登录脚本
站点基于 NexusPHP，登录成功后获取 access_token cookie。
"""

import os
import re
import sys
from pathlib import Path

# 确保能 import 同目录模块与项目根的 common 包
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SITE_DIR, "..", ".."))
for _p in (_SITE_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import cookies, env, http, search, sites

BASE_URL = "https://tjupt.org"
COOKIE_FILE = sites.cookie_path("tjupt") or Path(_SITE_DIR) / "tjupt_cookies.txt"

env.load_env()
USERNAME = env.get("TJPT_USERNAME")
PASSWORD = env.get("TJPT_PASSWORD")


def login(verbose=True):
    session = http.make_session(extra_headers={
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/login.php",
    })

    if not USERNAME or not PASSWORD:
        if verbose:
            print("  ✗ 未配置 TJPT_USERNAME / TJPT_PASSWORD (见项目根 .env)")
        return None

    # Step 1: 获取登录页面
    if verbose:
        print("[1/2] 访问登录页面...")
    resp = session.get(f"{BASE_URL}/login.php", timeout=15)
    if resp.status_code != 200:
        if verbose:
            print(f"  ✗ 无法访问登录页面 (HTTP {resp.status_code})")
        return None

    # Step 2: 提交登录
    if verbose:
        print("[2/2] 提交登录...")
    resp = session.post(
        f"{BASE_URL}/takelogin.php",
        data={"username": USERNAME, "password": PASSWORD},
        timeout=15,
        allow_redirects=True,
    )

    url = str(resp.url)

    # 异地登录保护
    if "异地登录保护" in resp.text or "异地登录" in resp.text:
        if verbose:
            print("  ✗ 异地登录保护，请使用上次登录的网络环境")
        ip_match = re.search(r'当前登录IP[：:]\s*([\d.]+)', resp.text)
        if ip_match and verbose:
            print(f"  当前 IP: {ip_match.group(1)}")
        return None

    # 登录成功 (不在登录相关页面)
    if "takelogin" not in url and "login.php" not in url:
        if verbose:
            print(f"  ✓ 登录成功！")
            print(f"  跳转至: {url}")
        title = search.extract_title(resp.text)
        if title and verbose:
            print(f"  页面标题: {title}")
        user_info = extract_user_info(resp.text)
        if user_info and verbose:
            print(f"  用户: {user_info}")
        cookies.save_key_value(session, COOKIE_FILE)
        return session

    # 响应判断
    if resp.status_code == 200:
        if "登录失败" in resp.text or "密码错误" in resp.text or "用户名或密码" in resp.text:
            if verbose:
                print("  ✗ 登录失败：用户名或密码错误")
            return None
        if "退出" in resp.text or "logout" in resp.text.lower():
            if verbose:
                print("  ✓ 登录成功（通过页面内容判断）")
            cookies.save_key_value(session, COOKIE_FILE)
            return session
        if verbose:
            print(f"  ? 未知状态，URL 为 {url}")
        return None

    if verbose:
        print(f"  ✗ 登录异常 (HTTP {resp.status_code})")
    return None


def extract_user_info(html):
    for pattern in [
        r'<a[^>]*userdetails[^>]*>(.*?)</a>',
        r'class="[^"]*username[^"]*"[^>]*>\s*(.*?)\s*<',
        r'欢迎.*?<b>(.*?)</b>',
    ]:
        m = re.search(pattern, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


if __name__ == "__main__":
    print("=" * 50)
    print("TJUPT 登录脚本")
    print("=" * 50)
    session = login(verbose=True)
    print("=" * 50)
    print("结果:", "成功 ✓" if session else "失败 ✗")
    print("=" * 50)
