"""根 .env 的定位、读取与写回。

来源: dmhypt/login.py 的 Config 类(load_dotenv + os.getenv)与
      save_cookie_to_env (L122-133), 目标路径统一为项目根 .env。

dotenv 为可选依赖: 安装了 python-dotenv 时优先使用(与 dmhy 原行为一致),
否则用内置的简易解析兜底(不覆盖已存在的环境变量)。
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv as _load_dotenv
except ImportError:  # 旧 conda 环境可能未装 python-dotenv
    _load_dotenv = None

# 项目根目录 (common/ 的上一级)
ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT_DIR / ".env"


def load_env() -> None:
    """加载根 .env(幂等,不覆盖已存在的环境变量)。"""
    if _load_dotenv is not None:
        _load_dotenv(ENV_FILE)
        return
    # 简易兜底解析: 逐行 KEY=VALUE,忽略注释与空行
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()


def get(key: str, default: str = "") -> str:
    """读取环境变量,未设置返回 default。"""
    return os.getenv(key, default)


def get_proxy() -> str:
    """HTTPS_PROXY or HTTP_PROXY or 空串。"""
    return os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY", "")


def write_env_value(key: str, value: str) -> None:
    """把 key=value 写回根 .env(已存在则替换该行,否则追加)。

    提取自 dmhy login.py save_cookie_to_env,目标文件改为 ENV_FILE。
    """
    lines = ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
