#!/usr/bin/env python3
"""独立检测脚本：检查本机 IP 是否仍被 azusa.wiki 风控封禁。

不依赖 azusa_login.py 的任何代码。原理：封禁期间服务器会在 cookie 验证前
就拒绝所有请求，所以用浏览器 UA 裸请求首页即可判断。
"""
import sys
import requests

BASE = "https://azusa.wiki"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# README 里记录的封禁提示
BAN_MARKERS = [
    "我们怀疑你在欺骗系统",
    "禁用了你的IP",
    "Login 锁定",
    "认证的最大错误尝试次数",
    "ip_banned",
    "被封",
]

def check(path, timeout=20):
    url = BASE + path
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout, allow_redirects=True)
    except requests.exceptions.SSLError as e:
        return None, f"SSL 错误: {e}"
    except requests.exceptions.RequestException as e:
        return None, f"请求异常: {e}"

    text = r.text
    hits = [m for m in BAN_MARKERS if m in text]
    # 正常页面应含的标识（NexusPHP 首页通常有登录框/logo）
    normal_markers = [m for m in ["请登录", "登录", "torrents.php", "NexusPHP"] if m in text]
    return r, f"status={r.status_code} len={len(text)} 封禁关键词={hits} 正常关键词={normal_markers}"


def main():
    results = []
    for path in ["/", "/index.php", "/torrents.php"]:
        r, msg = check(path)
        results.append((path, r, msg))
        print(f"GET {path:18s} -> {msg}")

    print("\n" + "=" * 60)
    any_r = [r for _, r, _ in results if r is not None]
    if not any_r:
        print("结论：所有请求都失败了（网络/SSL 层），无法判断封禁状态")
        return 1

    all_banned = all(
        r.status_code != 200
        or any(m in r.text for m in ["我们怀疑你在欺骗系统", "禁用了你的IP", "Login 锁定", "ip_banned"])
        for r in any_r
    )
    any_normal = any(r.status_code == 200 and "torrents.php" in r.text for r in any_r)

    if all_banned and not any_normal:
        print("结论：⚠️ 疑似仍处于封禁状态（所有页面均被拒绝或出现封禁提示）")
    elif any_normal:
        print("结论：✅ 已解封（首页正常返回 200 且包含站点内容）")
    else:
        print("结论：状态不明，需人工查看上面响应详情")

    return 0 if any_normal else 1


if __name__ == "__main__":
    sys.exit(main())
