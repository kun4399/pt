"""浏览器油猴 cookie 接收服务(零第三方依赖, 标准库 http.server)。

用途: 油猴脚本(pt-cookie-sender.user.js)把当前 PT 站 cookie POST 到
/api/cookie, 服务按站点格式落盘:
  azusa → azusa_cookies.txt (Netscape 7 列)
  tjupt → tjupt_cookies.txt (name=value 每行)
  dmhy  → cookies.pkl (pickle RequestsCookieJar, 与现有 load_pickle 兼容)
  ptclub→ cookies.json ({"cookies":[...]}, 与浏览器导出格式一致)

安全(公网经 frp 暴露, 必须):
  - COOKIE_SERVER_TOKEN 未配置时拒绝启动(require_token 抛 RuntimeError)
  - 请求头 X-Auth-Token 或 ?token= 参数, secrets.compare_digest 常量时间比较
  - 默认只绑 127.0.0.1(由 frp 转发); body 上限 1 MiB
  - 写路径全部由 common.sites 注册表推导, 无路径穿越
  - 日志脱敏: 绝不打印 cookie 值 / token / query
"""

import json
import logging
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import requests

from . import config, cookies as cookie_util
from . import env, sites

log = logging.getLogger("pt.common.cookie_server")

# 均可用 .env 调整(COOKIE_SERVER_HOST/PORT/MAX_BODY)
DEFAULT_HOST = config.get_str("COOKIE_SERVER_HOST", "127.0.0.1")  # 默认只绑回环, 由 frp 穿透
DEFAULT_PORT = config.get_int("COOKIE_SERVER_PORT", 8766)         # 本地与 frp 远程端口一致
MAX_BODY_BYTES = config.get_int("COOKIE_SERVER_MAX_BODY", 1_048_576)  # 1 MiB

# 每站关键认证 cookie(缺失 → 警告, 通常是 HttpOnly document.cookie 读不到)
CRITICAL_COOKIES = {
    "azusa": ("c_secure_uid", "c_session_token"),
    "tjupt": ("access_token",),
    "dmhy": ("nexusphp_u2",),
    "ptclub": ("c_secure_uid", "c_secure_pass"),
}

# 每站兜底 domain(油猴 payload 缺 domain 时补)
SITE_HOSTS = {"azusa": "azusa.wiki", "tjupt": "tjupt.org",
              "dmhy": "u2.dmhy.org", "ptclub": "pterclub.net"}


def require_token() -> str:
    """读取 .env COOKIE_SERVER_TOKEN; 缺失/为空抛 RuntimeError(拒绝启动)。"""
    token = env.get("COOKIE_SERVER_TOKEN")
    if not token:
        raise RuntimeError(
            ".env 未配置 COOKIE_SERVER_TOKEN(公网暴露必须). "
            "运行 deploy/install.sh 自动生成, 或手动追加随机值到 .env")
    return token


# ---------------------------------------------------------------------------
# 校验与保存
# ---------------------------------------------------------------------------

def _validate(payload: dict):
    """校验 payload; 返回 (payload, error)。合法时 error 为空串。"""
    site = payload.get("site")
    if site not in sites.site_keys():
        return None, f"site 必须是 {'|'.join(sites.site_keys())}"
    cookies_list = payload.get("cookies")
    if not isinstance(cookies_list, list) or not cookies_list:
        return None, "cookies 必须是非空数组"
    cleaned = []
    for c in cookies_list:
        if not isinstance(c, dict):
            continue
        name, value = c.get("name"), c.get("value")
        if not isinstance(name, str) or not name or not isinstance(value, str):
            continue
        cleaned.append(_normalize_cookie(c, site))
    if not cleaned:
        return None, "cookies 中没有有效的 name/value 项"
    payload = dict(payload)
    payload["cookies"] = cleaned
    return payload, ""


def _normalize_cookie(c: dict, site: str) -> dict:
    """补默认值: domain/path/secure/expires。"""
    out = dict(c)
    out.setdefault("domain", SITE_HOSTS[site])
    out.setdefault("path", "/")
    out.setdefault("secure", False)
    expires = out.get("expires")
    if isinstance(expires, str) and expires.isdigit():
        out["expires"] = int(expires)
    return out


def save_site_cookies(site: str, cookies_list: list) -> dict:
    """按站点格式落盘。返回 {"saved": N, "file": str, "warning": str|None}。"""
    path = sites.cookie_path(site)
    path.parent.mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    cookie_util.inject_browser_cookies(s, cookies_list)
    warning = None

    if site == "azusa":
        cookie_util.save_netscape(s, path, quiet=True)
    elif site == "tjupt":
        cookie_util.save_key_value(s, path, quiet=True)
    elif site == "dmhy":
        cookie_util.save_pickle(s, path)
    elif site == "ptclub":
        with open(path, "w") as f:
            json.dump({"saved_at": datetime.now(timezone.utc).isoformat(),
                       "cookies": cookies_list}, f, ensure_ascii=False, indent=2)

    # 关键 cookie 缺失告警(通常是 HttpOnly)
    missing = [n for n in CRITICAL_COOKIES[site]
               if n not in {c["name"] for c in cookies_list}]
    if missing:
        warning = (f"关键 cookie 缺失: {', '.join(missing)} "
                   "(可能是 HttpOnly, document.cookie 读不到)")

    return {"saved": len(cookies_list), "file": str(path), "warning": warning}


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

class CookieHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # 保活; 所有响应必须带 Content-Length

    token = ""                     # make_server 注入

    # ---- 响应工具 ----
    def _send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _parse_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return None

    def _check_auth(self):
        """X-Auth-Token 头优先, 其次 ?token= 参数; 常量时间比较。"""
        header = self.headers.get("X-Auth-Token", "")
        if header:
            return secrets.compare_digest(header, self.token)
        query = parse_qs(urlparse(self.path).query)
        param = query.get("token", [""])[0]
        return bool(param) and secrets.compare_digest(param, self.token)

    # ---- 路由 ----
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json(200, {"ok": True, "service": "pt-cookie-server"})
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/cookie":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        if not self._check_auth():
            log.warning("POST /api/cookie 鉴权失败 (from %s)", self.client_address[0])
            self._send_json(403, {"ok": False, "error": "unauthorized"})
            return
        payload = self._parse_body()
        if payload is None:
            self._send_json(400, {"ok": False, "error": "body 解析失败或超限"})
            return
        payload, err = _validate(payload)
        if err:
            self._send_json(400, {"ok": False, "error": err})
            return
        try:
            result = save_site_cookies(payload["site"], payload["cookies"])
        except Exception as e:
            log.warning("POST /api/cookie 保存失败: %s", e)
            self._send_json(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})
            return
        log.info("POST /api/cookie site=%s saved=%d file=%s warning=%s",
                 payload["site"], result["saved"], result["file"], result["warning"])
        self._send_json(200, {"ok": True, "site": payload["site"],
                              "saved": result["saved"], "file": result["file"],
                              "warning": result["warning"]})

    def log_message(self, fmt, *args) -> None:
        """覆写: 只记方法/路径/状态码/长度, 绝不打印 query(?token=) 与 cookie 值。"""
        log.info("%s %s %s %s", self.command,
                 urlparse(self.path).path, self.request_version, args[0])


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                token: str = "") -> ThreadingHTTPServer:
    """创建 cookie 接收服务。token 注入 handler。"""
    CookieHandler.token = token
    server = ThreadingHTTPServer((host, port), CookieHandler)
    server.allow_reuse_address = True
    return server
