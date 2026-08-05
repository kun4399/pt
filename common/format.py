"""展示层格式化工具(原样取自 ptclub/pterclub.py L39-60)。"""

import re


def human_size(val) -> str:
    """字节数转人类可读格式 ("x.x GB")。"""
    if val is None:
        return "?"
    try:
        val = float(val)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if val < 1024:
                return f"{val:.1f} {unit}"
            val /= 1024
    except (TypeError, ValueError):
        return str(val)
    return f"{val:.1f} PB"


def human_time(t) -> str:
    """解析 "N天N时/N时N分/N分" 存活时间为短格式。"""
    if t is None:
        return "?"
    t = str(t).strip()
    m = re.match(r"(\d+)\s*天\s*(\d+)", t)
    if m:
        return f"{m.group(1)}天{m.group(2)}时"
    m = re.match(r"(\d+)\s*时\s*(\d+)", t)
    if m:
        return f"{m.group(1)}时{m.group(2)}分"
    m = re.match(r"(\d+)\s*分", t)
    if m:
        return f"{m.group(1)}分"
    return t
