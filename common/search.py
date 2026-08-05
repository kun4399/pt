"""跨站重复的搜索解析原语。

来源: extract_title — tjupt_login.py L91-93 / azusa_login.py 内联同款;
      parse_size — 合并 azusa_login.py L505-511 与 tjupt_search.py L153-157;
      safe_int — 合并 dmhy.py L328-332(_int) 与 pterclub.py L175-179(_num);
      build_download_url — 统一 azusa_login.py L473 / tjupt_search.py L107-108 /
                            pterclub.py L152-154 的下载链接拼装。
"""

import re


def extract_title(html) -> str | None:
    """提取 <title> 文本,失败返回 None。"""
    m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
    return m.group(1).strip() if m else None


def parse_size(text) -> tuple:
    """解析 "373.44 MB" / "21.06\nGiB" 等尺寸文本。

    返回 (value, unit);解析失败返回 (None, "")。
    兼容 azusa 的宽松模式(任意字母单位)。
    """
    if not text:
        return None, ""
    t = str(text).strip()
    m = re.search(r"([\d,.]+)\s*(TiB|GiB|MiB|KiB|TB|GB|MB|KB)", t, re.IGNORECASE)
    if not m:
        m = re.match(r"([\d.]+)\s*(\w+)", t)
    if not m:
        return None, ""
    try:
        val = float(m.group(1).replace(",", ""))
    except ValueError:
        return None, ""
    return val, m.group(2)


def safe_int(text, default=0):
    """安全转 int;失败返回 default。"""
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return default


def build_download_url(base_url: str, tid, passkey: str = "") -> str:
    """构造下载链接: {base}/download.php?id={tid}[&passkey={passkey}]。"""
    base = str(base_url).rstrip("/")
    url = f"{base}/download.php?id={tid}"
    if passkey:
        url += f"&passkey={passkey}"
    return url
