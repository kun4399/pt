#!/usr/bin/env python3
"""诊断脚本: 查看异地登录保护页面的表单结构"""
import os
import re
import sys

import requests

# 确保能 import 项目根的 common 包
_SITE_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_SITE_DIR, "..", ".."))
for _p in (_SITE_DIR, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import env, http

BASE_URL = "https://tjupt.org"

env.load_env()
USERNAME = env.get("TJPT_USERNAME")
PASSWORD = env.get("TJPT_PASSWORD")

session = http.make_session(extra_headers={
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/login.php",
})

# 先登录触发异地保护
session.get(f"{BASE_URL}/login.php", timeout=15)
resp = session.post(f"{BASE_URL}/takelogin.php",
                    data={"username": USERNAME, "password": PASSWORD},
                    timeout=15, allow_redirects=False)

print(f"Status: {resp.status_code}")
print(f"Cookies: {len(session.cookies)} 个")
for c in session.cookies:
    print(f"  {c.name} = {c.value[:80] if len(c.value) > 80 else c.value}")

# 提取页面上所有 input/select/textarea
html = resp.text
print("\n=== 表单字段 ===")
for tag in re.findall(r'<(input|select|textarea|button)[^>]*>', html, re.IGNORECASE):
    pass
# 更全面的提取
inputs = re.findall(r'<(input|select|textarea)\b([^>]*)>', html, re.IGNORECASE)
for tag_type, attrs in inputs:
    name = re.search(r'name\s*=\s*["\']([^"\']+)["\']', attrs)
    type_ = re.search(r'type\s*=\s*["\']([^"\']+)["\']', attrs)
    value = re.search(r'value\s*=\s*["\']([^"\']*)["\']', attrs)
    placeholder = re.search(r'placeholder\s*=\s*["\']([^"\']*)["\']', attrs)
    print(f"  {tag_type}: name={name.group(1) if name else '?'}"
          f"  type={type_.group(1) if type_ else '?'}"
          f"  value={value.group(1) if value else '?'}"
          f"  placeholder={placeholder.group(1) if placeholder else ''}")

# 提取所有文本/提示
print("\n=== 页面关键文本 ===")
texts = re.findall(r'>([^<]{10,200})<', html)
for t in texts[:30]:
    t = t.strip()
    if t:
        print(f"  {t}")

# 检查是否发送了邮箱
print("\n=== 邮箱相关 ===")
emails = re.findall(r'[\w.-]+@[\w.-]+', html)
for e in set(emails):
    print(f"  {e}")

# 表单 action
forms = re.findall(r'<form\b([^>]*)>', html, re.IGNORECASE)
for f in forms:
    action = re.search(r'action\s*=\s*["\']([^"\']+)["\']', f)
    method = re.search(r'method\s*=\s*["\']([^"\']+)["\']', f)
    print(f"\nForm: action={action.group(1) if action else '?'}  method={method.group(1) if method else '?'}")
