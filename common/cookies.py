"""四种 cookie 格式的存取(原样逻辑,格式不统一)。

来源: load/save_netscape — azusapt/azusa_login.py L695-727 (Netscape 7 列);
      save_key_value — tjupt/tjupt_login.py L108-116 (name=value 单行);
      load/save_pickle — dmhypt/login.py L96-113 (pickle 序列化);
      load_browser_json / inject_browser_cookies — ptclub/pterclub.py L65-69 / L80-87。
"""

import json
import logging
import pickle
from pathlib import Path

import requests

log = logging.getLogger("pt.common.cookies")


# ---- Netscape 格式 (azusa) ----

def load_netscape(session: requests.Session, path) -> bool:
    """从 Netscape 7 列格式文件加载 cookies 到 session。返回是否加载成功。"""
    p = Path(path)
    if not p.exists():
        print(f"Cookie 文件不存在: {p}")
        return False

    try:
        with open(p, "r") as f:
            count = 0
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) == 7:
                    session.cookies.set(
                        parts[5], parts[6],
                        domain=parts[0], path=parts[2],
                    )
                    count += 1
        print(f"已加载 {count} 个 cookie: {p}")
        return count > 0
    except Exception as e:
        print(f"Cookie 加载失败: {e}")
        return False


def save_netscape(session: requests.Session, path) -> None:
    """保存 cookies 到 Netscape 格式文件。"""
    p = Path(path)
    with open(p, "w") as f:
        for cookie in session.cookies:
            f.write(f"{cookie.domain}\tTRUE\t{cookie.path}\t"
                    f"{'TRUE' if cookie.secure else 'FALSE'}\t"
                    f"{cookie.expires if cookie.expires else 0}\t"
                    f"{cookie.name}\t{cookie.value}\n")
    print(f"Cookie 已保存到: {p}")


# ---- name=value 单行格式 (tjupt) ----

def save_key_value(session: requests.Session, path) -> int:
    """以 name=value 每行一条写出 cookies,返回条数。"""
    p = Path(path)
    with open(p, "w") as f:
        for cookie in session.cookies:
            f.write(f"{cookie.name}={cookie.value}\n")
    n = len(session.cookies)
    print(f"  ✓ 已保存 {n} 条 cookies → {p}")
    return n


# ---- pickle 格式 (dmhy) ----

def save_pickle(session: requests.Session, path) -> None:
    with open(path, "wb") as f:
        pickle.dump(session.cookies, f)
    log.info("Cookies saved → %s", path)


def load_pickle(path) -> requests.Session | None:
    """从 pickle 恢复 session(仅 cookies),失败返回 None。"""
    p = Path(path)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as f:
            cookies = pickle.load(f)
        s = requests.Session()
        s.cookies = cookies
        return s
    except Exception as e:
        log.warning("Failed to load cookies: %s", e)
        return None


# ---- 浏览器导出 JSON 格式 (ptclub) ----

def load_browser_json(path) -> list | None:
    """读浏览器导出的 {"cookies": [...]} JSON,失败返回 None。"""
    p = Path(path)
    if not p.exists():
        return None
    with open(p) as f:
        return json.load(f).get("cookies", [])


def inject_browser_cookies(session: requests.Session, cookies: list) -> None:
    """把 JSON 条目 [{name, value, domain, path, secure}, ...] 注入 session。"""
    for c in cookies:
        session.cookies.set(
            c["name"], c["value"],
            domain=c.get("domain"),
            path=c.get("path", "/"),
            secure=c.get("secure", False),
        )
