"""PT 站点注册表 + 登录前预检 + 搜索结果归一化。

统一入口(pt_search.py / common/unified.py)依赖本模块;各站独立脚本不依赖。
- 站点注册表: 名称/URL/登录页/代理来源/次数解析器,一处维护
- precheck(): 只 GET 登录页(不做登录 POST),检测网络可达性 + 剩余登录次数,
  ≤2 输出警告且不登录(azusa/dmhy 阈值统一为 ATTEMPTS_WARN=2)
- normalize_result(): 各站搜索原始字段 → 统一 schema(UNIFIED_FIELDS)

次数解析与站内现有实现同一套规则:
  azusa 正则同 azusa_login.py get_login_page("还有 N 次"),
  dmhy 选择器同 login.py get_attempts(span.attempt-left-counter)。
"""

import re
from pathlib import Path

from . import cookies, env, format as fmt, http

# 统一搜索结果的字段顺序(dict key 全集)
UNIFIED_FIELDS = (
    "site", "site_name", "category", "title", "subtitle", "size",
    "seeders", "leechers", "completed", "upload_time",
    "uploader", "tags", "promotion", "details_url", "download_url",
)

# 剩余次数 ≤2 时输出警告且不登录
ATTEMPTS_WARN = 2
PREPCHECK_TIMEOUT = 15

# 各站登录页(预检 GET 目标)
SITES = {
    "azusa": {
        "name": "azusa.wiki",
        "dir": "azusapt",
        "base_url": "https://azusa.wiki",
        "login_page": "https://azusa.wiki/index.php?title=Special:UserLogin",
        "login_type": "password_captcha",
        "proxy": lambda: env.get("AZUSA_PROXY"),   # 默认 AZUSA_PROXY(曾直连封禁)
        "module": "sites.azusapt.azusa_login",
        "attempts": "_parse_azusa_attempts",
        "cookie_file": "azusa_cookies.txt",        # 相对站点目录
    },
    "tjupt": {
        "name": "tjupt.org",
        "dir": "tjupt",
        "base_url": "https://tjupt.org",
        "login_page": "https://tjupt.org/login.php",
        "login_type": "password",
        "proxy": lambda: "",                       # 永远直连(拒绝非中国 IP)
        "module": "sites.tjupt.tjupt_login",
        "attempts": None,                          # 无次数机制 → N/A
        "cookie_file": "tjupt_cookies.txt",
    },
    "dmhy": {
        "name": "u2.dmhy.org",
        "dir": "dmhypt",
        "base_url": "https://u2.dmhy.org",
        "login_page": "https://u2.dmhy.org/takelogin.php",
        "login_type": "password_captcha",
        "proxy": env.get_proxy,                    # 全局代理
        "module": "sites.dmhypt.dmhy",
        "attempts": "_parse_dmhy_attempts",
        "cookie_file": "cookies.pkl",              # pickle, load_pickle 专用
    },
    "ptclub": {
        "name": "pterclub.net",
        "dir": "ptclub",
        "base_url": "https://pterclub.net",
        "login_page": "https://pterclub.net/index.php",
        "login_type": "cookie_only",               # Cloudflare Turnstile, 不自动登录
        "proxy": env.get_proxy,
        "module": "sites.ptclub.pterclub",
        "attempts": None,
        "cookie_file": "cookies.json",             # 浏览器导出
    },
}


# ---------------------------------------------------------------------------
# 注册表访问
# ---------------------------------------------------------------------------

def site_keys() -> list:
    return list(SITES.keys())


def get_site(key: str) -> dict:
    """按 key 取站点元数据;未知 key 抛 ValueError(带可用列表)。"""
    if key not in SITES:
        raise ValueError(f"未知站点: {key} (可用: {', '.join(SITES)})")
    return SITES[key]


def resolve_proxy(key: str, override: str = "") -> str:
    """站点实际代理: override 优先;tjupt 恒为空(直连)。"""
    if key == "tjupt":
        return ""
    if override:
        return override
    return get_site(key)["proxy"]() or ""


def cookie_path(site_key: str) -> Path | None:
    """站点 cookie 文件绝对路径;无则返回 None。目录名与 site_key 可不同(azusa→azusapt)。"""
    site = get_site(site_key)
    fname = site.get("cookie_file")
    if not fname:
        return None
    return Path(__file__).resolve().parent.parent / "sites" / site["dir"] / fname


# ---------------------------------------------------------------------------
# 剩余次数解析(与各站登录脚本同一套规则)
# ---------------------------------------------------------------------------

def _parse_azusa_attempts(html: str):
    """azusa: "你还有 [N] 次尝试机会"(数字常被标签包裹,先剥标签)。返回 (remaining, None)。"""
    m = re.search(r"还有\s*(?:\[(\d+)\]|(\d+))\s*次", re.sub(r"<[^>]+>", "", html))
    if m:
        return int(m.group(1) or m.group(2)), None
    return None


def _parse_dmhy_attempts(html: str):
    """dmhy: span.attempt-left-counter / attempt-full-counter。返回 (remaining, total)。"""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        left = soup.find("span", class_="attempt-left-counter")
        full = soup.find("span", class_="attempt-full-counter")
        if left and full:
            return int(left.text.strip()), int(full.text.strip())
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 登录前预检(只 GET, 不做登录 POST)
# ---------------------------------------------------------------------------

def precheck(site_key: str, timeout: int = PREPCHECK_TIMEOUT) -> dict:
    """检测站点网络可达性 + 剩余登录次数 + 当前登录态。

    返回:
      {"site", "reachable", "http_status", "attempts_remaining", "attempts_total",
       "logged_in", "warning"(剩余≤2), "blocked"(风控致命关键词), "error", "detail"}
      attempts_remaining: int | None(该站无次数机制 → None, 显示 N/A)
      logged_in: bool | None(None = 无本地 cookie 可验证; ptclub 为真实判定)
    """
    site = get_site(site_key)
    proxy = resolve_proxy(site_key)
    session = http.make_session(proxy=proxy)

    result = {
        "site": site_key, "reachable": False, "http_status": None,
        "attempts_remaining": None, "attempts_total": None,
        "logged_in": None, "warning": False, "blocked": False,
        "error": None, "detail": "",
    }

    # 1. GET 登录页(网络可达性 + 次数)
    try:
        resp = session.get(site["login_page"], timeout=timeout, allow_redirects=True)
        result["http_status"] = resp.status_code
        result["reachable"] = resp.status_code == 200
        if not result["reachable"]:
            result["error"] = f"HTTP {resp.status_code}"
            result["detail"] = f"登录页返回 HTTP {resp.status_code}"
            return result
        html = resp.text
    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        result["detail"] = f"无法访问 {site['login_page']}"
        return result

    # 2. 剩余次数
    parser_name = site.get("attempts")
    if parser_name:
        parsed = globals()[parser_name](html)
        if parsed:
            result["attempts_remaining"], result["attempts_total"] = parsed
    # 3. 警告(≤2 不登录)
    if result["attempts_remaining"] is not None and result["attempts_remaining"] <= ATTEMPTS_WARN:
        result["warning"] = True
        result["detail"] = f"仅剩 {result['attempts_remaining']} 次, 不执行登录"
    else:
        result["detail"] = "ok"

    # 4. 风控致命关键词(azusa)
    if site_key == "azusa":
        for kw in ("登录锁定", "禁用了你的IP", "最大错误尝试次数"):
            if kw in html:
                result["blocked"] = True
                result["detail"] = f"命中风控: {kw}"

    # 5. 当前登录态(有本地 cookie 才验证)
    result["logged_in"] = _check_logged_in(site_key, session, timeout)
    return result


def login_check(site_key: str, session, timeout: int = 30) -> bool:
    """用当前 session(已带 cookie)验证登录态。

    与各站站内判定同一套参数:
      azusa  与 ensure_ready_session 回退判定一致(c_secure_uid + 登录标题排除)
      tjupt  首页未登录会 302 → login.php, 页面含"退出"视为已登录
      dmhy   与 dmhy.py _ensure_logged_in 一致(logout/usercp)
      ptclub 复用站内 check_login(自加载 cookies.json)
    """
    site = get_site(site_key)
    base = site["base_url"]
    if site_key == "azusa":
        return http.is_logged_in(
            session, f"{base}/index.php",
            fail_keywords=("我们怀疑你在欺骗系统", "禁用了你的IP",
                           "Login 锁定", "最大错误尝试次数"),
            cookie_names=("c_secure_uid",),
            title_excludes=("登录",), timeout=timeout)
    if site_key == "tjupt":
        return http.is_logged_in(
            session, f"{base}/index.php",
            fail_keywords=("login.php",),
            success_keywords=("退出", "logout"),
            timeout=timeout)
    if site_key == "dmhy":
        return http.is_logged_in(session, f"{base}/",
                                 success_keywords=("logout", "usercp"),
                                 timeout=timeout)
    if site_key == "ptclub":
        try:
            import importlib
            mod = importlib.import_module(site["module"])
            return bool(mod.check_login(resolve_proxy(site_key)))
        except Exception:
            return False
    return False


def _check_logged_in(site_key: str, session, timeout: int) -> bool | None:
    """用本地 cookie 验证登录态;无 cookie 文件/加载失败返回 None。"""
    site = get_site(site_key)
    path = cookie_path(site_key)

    if site_key == "ptclub":
        return login_check(site_key, session, timeout)

    if not path or not path.exists():
        return None
    try:
        if site_key == "azusa":
            cookies.load_netscape(session, path, quiet=True)
        elif site_key == "tjupt":
            cookies.load_key_value(session, path, domain="tjupt.org")
        elif site_key == "dmhy":
            s = cookies.load_pickle(path)
            if s is None:
                return None
            s.headers.update(session.headers)
            if session.proxies:
                s.proxies = session.proxies
            session = s
    except Exception:
        return None
    return login_check(site_key, session, timeout)


def precheck_all(timeout: int = PREPCHECK_TIMEOUT) -> dict:
    """顺序预检全部站点,单站异常不拖垮整体。返回 {site_key: precheck_result}。"""
    out = {}
    for key in site_keys():
        try:
            out[key] = precheck(key, timeout)
        except Exception as e:
            out[key] = {"site": key, "reachable": False, "http_status": None,
                        "attempts_remaining": None, "attempts_total": None,
                        "logged_in": None, "warning": False, "blocked": False,
                        "error": f"{type(e).__name__}: {e}", "detail": "预检异常"}
    return out


# ---------------------------------------------------------------------------
# 搜索结果归一化 → 统一 schema
# ---------------------------------------------------------------------------

def normalize_result(site_key: str, raw: dict) -> dict:
    """各站搜索原始字段 → UNIFIED_FIELDS。映射规则注册在 _NORMALIZERS。"""
    norm = _NORMALIZERS[site_key](raw)
    out = {"site": site_key, "site_name": get_site(site_key)["name"]}
    for f in UNIFIED_FIELDS[2:]:           # site/site_name 已置
        out[f] = norm.get(f, "" if f in ("category", "title", "subtitle", "size",
                                         "upload_time", "uploader") else None)
    out["tags"] = norm.get("tags", []) or []
    out["extra"] = norm.get("extra", {})
    return out


def _norm_azusa(raw: dict) -> dict:
    size = fmt.join_size(raw.get("size_value"), raw.get("size_unit"))
    if not size:
        size = raw.get("size_raw", "")
    return {
        "category": raw.get("category", ""),
        "title": raw.get("title", ""),
        "subtitle": raw.get("subtitle", ""),
        "size": size,
        "seeders": raw.get("seeders"),
        "leechers": raw.get("leechers"),
        "completed": raw.get("completed"),
        "upload_time": fmt.human_time(raw.get("upload_time_label", "")),
        "uploader": "",
        "tags": raw.get("tags", []),
        "promotion": raw.get("promotion", ""),
        "details_url": raw.get("detail_url", ""),
        "download_url": raw.get("download_url", ""),
        "extra": {"id": raw.get("id"), "comments": raw.get("comments"),
                  "is_hot": raw.get("is_hot", False),
                  "sticky_level": raw.get("sticky_level", 0)},
    }


def _norm_tjupt(raw: dict) -> dict:
    return {
        "category": raw.get("category", ""),
        "title": raw.get("title", ""),
        "subtitle": raw.get("subtitle", ""),
        "size": fmt.join_size(raw.get("size"), raw.get("size_unit")),
        "seeders": raw.get("seeders"),
        "leechers": raw.get("leechers"),
        "completed": raw.get("snatched"),
        "upload_time": raw.get("upload_time", ""),
        "uploader": raw.get("uploader", ""),
        "tags": [],
        "promotion": "",
        "details_url": raw.get("url", ""),
        "download_url": raw.get("download_url", ""),
        "extra": {"id": raw.get("id"), "comments": raw.get("comments")},
    }


def _norm_dmhy(raw: dict) -> dict:
    return {
        "category": raw.get("category", ""),
        "title": raw.get("title", ""),
        "subtitle": raw.get("subtitle", ""),
        "size": raw.get("size", ""),
        "seeders": raw.get("seeders"),
        "leechers": raw.get("leechers"),
        "completed": raw.get("completed"),
        "upload_time": raw.get("survival", ""),
        "uploader": "",
        "tags": [],
        "promotion": "",
        "details_url": raw.get("details_url", ""),
        "download_url": raw.get("download_url", ""),
        "extra": {"rating": raw.get("rating"), "comments": raw.get("comments")},
    }


def _norm_ptclub(raw: dict) -> dict:
    return {
        "category": raw.get("category", ""),
        "title": raw.get("title", ""),
        "subtitle": raw.get("subtitle", ""),
        "size": raw.get("size", ""),
        "seeders": raw.get("seeders"),
        "leechers": raw.get("leechers"),
        "completed": raw.get("completed"),
        "upload_time": fmt.human_time(raw.get("alive_time", "")),
        "uploader": raw.get("uploader", ""),
        "tags": raw.get("tags", []),
        "promotion": "",
        "details_url": raw.get("details_url", ""),
        "download_url": raw.get("download_url", ""),
        "extra": {},
    }


_NORMALIZERS = {
    "azusa": _norm_azusa,
    "tjupt": _norm_tjupt,
    "dmhy": _norm_dmhy,
    "ptclub": _norm_ptclub,
}
