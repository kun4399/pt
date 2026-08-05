"""展示层格式化工具(原样取自 ptclub/pterclub.py L39-60;join_size 为统一入口新增)。"""

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


def join_size(value, unit) -> str:
    """数值 + 单位 → "373.44 MB"(统一入口的 size 字段格式)。

    兼容 float("373.44")+("MB") 与字符串("373.44 MB")两种输入;
    解析失败时原样返回 str(value)。
    """
    if value is None or value == "":
        return str(unit or "")
    if unit:
        try:
            return f"{float(value):,.2f} {unit}"
        except (TypeError, ValueError):
            return f"{value} {unit}"
    # 无单位: 原样返回(可能已是 "373.44 MB" 字符串)
    return str(value)
