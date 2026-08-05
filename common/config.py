"""统一配置读取(基于根目录 .env, 类型化)。

所有"用户可修改"的配置集中在一个地方: 项目根 .env(模板见 .env.example)。
本模块提供类型化读取, 各脚本不再硬编码端口/超时/重试次数等用户可调参数。

用法:
  from common import config
  port = config.get_int("COOKIE_SERVER_PORT", 8766)
  warn = config.get_int("ATTEMPTS_WARN", 2)
  flag = config.get_bool("SOME_FLAG", False)

读取时自动确保 .env 已加载(load_env 幂等), 任何模块/时机调用都安全。
"""

from . import env


def get_int(key: str, default: int = 0) -> int:
    """读 .env 整数配置; 缺失/非法返回 default。"""
    env.load_env()
    v = env.get(key)
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float = 0.0) -> float:
    """读 .env 浮点配置; 缺失/非法返回 default。"""
    env.load_env()
    v = env.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    """读 .env 布尔配置(1/true/yes/on 视为 True); 缺失返回 default。"""
    env.load_env()
    v = env.get(key)
    if not v:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def get_str(key: str, default: str = "") -> str:
    """读 .env 字符串配置; 缺失返回 default。"""
    env.load_env()
    return env.get(key) or default
