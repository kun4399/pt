"""四站统一搜索适配器 + 输出渲染(供 pt_search.py 使用)。

- search_site(): 单站统一搜索,复用各站现有函数(最大复用,零重复实现)
  azusa 走 azusa_login(cookie-first, 失效才登录);tjupt 走 tjupt_login+tjupt_search;
  dmhy 走 dmhy._load_session+search(cookie 模式, 不自动登录);
  ptclub 走 pterclub.check_login+search。
- search_all(): 默认全部站点,单站失败不拖垮整体。
- render_table()/render_json(): 统一输出(表格含站点来源列;JSON 为权威格式)。

各站登录态判定参数统一收敛在 common/sites.login_check()。
"""

import importlib
import json
from datetime import datetime, timezone

from . import sites

# 统一入口 cookie-first: 本地 cookie 有效则不再登录(azusa 风控最高, 避免每次登录)
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_REFUSED = "refused"          # 剩余次数 ≤2, 拒绝登录
STATUS_LOGIN_FAILED = "login_failed"
STATUS_COOKIE_INVALID = "cookie_invalid"
STATUS_NETWORK_ERROR = "network_error"


def _load_module(site_key: str):
    return importlib.import_module(sites.get_site(site_key)["module"])


def _fail(site_key, status, error) -> dict:
    return {"site": site_key, "site_name": sites.get_site(site_key)["name"],
            "ok": False, "status": status, "error": error,
            "total": 0, "results": [], "raw": None}


def _ok(site_key, results, total, raw) -> dict:
    status = STATUS_EMPTY if not results else STATUS_OK
    return {"site": site_key, "site_name": sites.get_site(site_key)["name"],
            "ok": True, "status": status, "error": None,
            "total": total, "results": results, "raw": raw}


# ---------------------------------------------------------------------------
# 单站搜索
# ---------------------------------------------------------------------------

def search_site(site_key: str, keyword: str, *, limit: int = 20, page: int = 0,
                proxy: str = "", force_login: bool = False,
                timeout: int = 30, incldead: int = 0) -> dict:
    """统一单站搜索。返回 {site, site_name, ok, status, error, total, results, raw}。

    results 为已归一化(unified schema)的列表;total 为该站搜索到的总数(站点估计)。
    status ∈ {ok, empty, refused, login_failed, cookie_invalid, network_error}
    """
    if site_key not in sites.site_keys():
        return _fail(site_key, STATUS_NETWORK_ERROR, f"未知站点: {site_key}")
    try:
        if site_key == "azusa":
            return _azusa_search(keyword, limit, page, proxy, force_login, timeout, incldead)
        if site_key == "tjupt":
            return _tjupt_search(keyword, limit, page, proxy, force_login, timeout, incldead)
        if site_key == "dmhy":
            return _dmhy_search(keyword, limit, proxy, timeout)
        if site_key == "ptclub":
            return _ptclub_search(keyword, limit, proxy, timeout)
    except Exception as e:
        return _fail(site_key, STATUS_NETWORK_ERROR, f"{type(e).__name__}: {e}")
    return _fail(site_key, STATUS_NETWORK_ERROR, "未知站点")


def _azusa_search(keyword, limit, page, proxy, force_login, timeout, incldead):
    from common import cookies, http
    mod = _load_module("azusa")
    session = http.make_session(proxy=proxy)

    # cookie-first: 本地 cookie 有效则直接搜索, 不登录(风控保护)
    if not force_login:
        p = sites.cookie_path("azusa")
        if p and p.exists():
            cookies.load_netscape(session, p, quiet=True)
            if sites.login_check("azusa", session, timeout):
                try:
                    return _azusa_search_with(mod, session, keyword, limit, page, incldead, timeout)
                except RuntimeError:
                    pass  # cookie 已过期(标题检查误判), 落到下方重新登录

    login_session, reason = mod.login(proxy=proxy)
    if login_session is None:
        if reason in ("refused", "fatal"):
            return _fail("azusa", STATUS_REFUSED, "剩余尝试次数不足或风控, 拒绝登录")
        return _fail("azusa", STATUS_LOGIN_FAILED, "登录失败(验证码或网络)")
    session = login_session

    try:
        return _azusa_search_with(mod, session, keyword, limit, page, incldead, timeout)
    except RuntimeError as e:
        # search_torrents 抛 "Session 未登录"(cookie 过期), 再登录一次重试
        login_session, reason = mod.login(proxy=proxy)
        if login_session is None:
            return _fail("azusa", STATUS_LOGIN_FAILED, f"重新登录失败: {e}")
        return _azusa_search_with(mod, login_session, keyword, limit, page, incldead, timeout)


def _azusa_search_with(mod, session, keyword, limit, page, incldead, timeout):
    data = mod.search_torrents(session, keyword, page=page, incldead=incldead)
    results = data.get("results", [])[:limit]
    total = data.get("total_results_estimate", len(results))
    return _ok("azusa", [sites.normalize_result("azusa", r) for r in results],
               total, data)


def _tjupt_search(keyword, limit, page, proxy, force_login, timeout, incldead):
    from common import cookies, http
    mod_login = _load_module("tjupt")
    mod_search = importlib.import_module("sites.tjupt.tjupt_search")
    session = http.make_session()  # tjupt 永远直连, proxy 恒忽略

    # cookie-first
    if not force_login:
        p = sites.cookie_path("tjupt")
        if p and p.exists():
            cookies.load_key_value(session, p, domain="tjupt.org")
            if sites.login_check("tjupt", session, timeout):
                return _tjupt_search_with(mod_search, session, keyword, limit, page, incldead, timeout)

    login_session = mod_login.login(verbose=False)
    if login_session is None:
        return _fail("tjupt", STATUS_LOGIN_FAILED,
                     "登录失败(可能触发异地登录保护, 需在常用网络/IP 下登录)")
    session = login_session
    # 登录后自行验证(login() 返回 session 不代表一定成功)
    if not sites.login_check("tjupt", session, timeout):
        return _fail("tjupt", STATUS_LOGIN_FAILED, "登录后验证未通过(异地登录保护?)")
    return _tjupt_search_with(mod_search, session, keyword, limit, page, incldead, timeout)


def _tjupt_search_with(mod_search, session, keyword, limit, page, incldead, timeout):
    data = mod_search.search(keyword=keyword, page=page, incldead=incldead, session=session)
    if data.get("error"):
        return _fail("tjupt", STATUS_NETWORK_ERROR, data["error"])
    results = data.get("results", [])[:limit]
    # total_results=0(站点未给出精确数)时回退为已解析条数
    total = data.get("pagination", {}).get("total_results") or len(results)
    return _ok("tjupt", [sites.normalize_result("tjupt", r) for r in results],
               total, data)


def _dmhy_search(keyword, limit, proxy, timeout):
    mod = _load_module("dmhy")
    session = mod._load_session(proxy)
    if session is None or not sites.login_check("dmhy", session, timeout):
        return _fail("dmhy", STATUS_COOKIE_INVALID,
                     "cookies.pkl 缺失或已过期, 请先运行 sites/dmhypt/login.py")
    data = mod.search(session, keyword, limit=limit, timeout=timeout)
    if not data.get("success"):
        return _fail("dmhy", STATUS_NETWORK_ERROR, data.get("message", "搜索失败"))
    results = data.get("results", [])
    return _ok("dmhy", [sites.normalize_result("dmhy", r) for r in results],
               len(results), data)


def _ptclub_search(keyword, limit, proxy, timeout):
    mod = _load_module("ptclub")
    # 先 check_login, 避免 search() 内部 print "Cookie 已失效" 污染统一输出
    if not mod.check_login(proxy):
        return _fail("ptclub", STATUS_COOKIE_INVALID,
                     "cookies.json 缺失或已过期, 请用浏览器重新导出")
    results = mod.search(keyword, max_results=limit, proxy=proxy)
    return _ok("ptclub", [sites.normalize_result("ptclub", r) for r in results],
               len(results), results)


# ---------------------------------------------------------------------------
# 全站搜索
# ---------------------------------------------------------------------------

def search_all(keyword: str, keys: list | None = None, **kw) -> list:
    """默认全部站点;单站失败独立上报, 不中断其他站。返回 [report, ...]。"""
    keys = keys or sites.site_keys()
    return [search_site(k, keyword, **kw) for k in keys]


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def _clean(s) -> str:
    """去除不可见字符(零宽/软连字符等, 如 dmhy 存活时间中的 U+00AD)。"""
    return "".join(c for c in str(s) if c.isprintable() or c in "\n\t")


def _dw(s) -> int:
    """显示宽度: 中文等宽字符按 2 计。"""
    return sum(2 if ord(c) > 127 else 1 for c in _clean(s))


def _pad(s, width) -> str:
    """按显示宽度左对齐补齐。"""
    s = _clean(s)
    return s + " " * max(0, width - _dw(s))


def _cut(s, width) -> str:
    """按显示宽度截断, 超长加 "..."。"""
    s = _clean(s)
    if _dw(s) <= width:
        return s
    out, w = "", 0
    for c in s:
        cw = 2 if ord(c) > 127 else 1
        if w + cw > width - 3:
            break
        out += c
        w += cw
    return out + "..."

STATUS_LABEL = {
    STATUS_OK: "ok",
    STATUS_EMPTY: "无结果",
    STATUS_REFUSED: "拒绝登录(次数不足/风控)",
    STATUS_LOGIN_FAILED: "登录失败",
    STATUS_COOKIE_INVALID: "cookie 失效",
    STATUS_NETWORK_ERROR: "网络错误",
}


def render_table(reports: list, keyword: str, verbose: bool = False) -> str:
    """统一表格输出, 首列站点来源。"""
    lines = []
    ok_reports = [r for r in reports if r["ok"]]
    failed = [r for r in reports if not r["ok"]]
    lines.append(f"=== PT 站搜索: \"{keyword}\" ({len(reports)} 站, "
                 f"{len(ok_reports)} 站返回结果) ===")

    headers = [("站点", 6), ("类型", 8), ("大小", 12), ("做种", 5),
               ("下载", 5), ("完成", 6), ("时间", 12), ("标题", 0)]
    head = "".join(_pad(h, w) for h, w in headers[:-1]) + headers[-1][0]
    lines.append(head)
    lines.append("-" * min(100, _dw(head)))

    for r in ok_reports:
        for item in r["results"]:
            title = item.get("title", "")
            if item.get("promotion"):
                title = f"[{item['promotion']}] {title}"
            row = (_pad(r["site"], 6)
                   + _cut(item.get("category", ""), 8)
                   + _pad(item.get("size", ""), 12)
                   + _pad(item.get("seeders") or 0, 5)
                   + _pad(item.get("leechers") or 0, 5)
                   + _pad(item.get("completed") or 0, 6)
                   + _cut(item.get("upload_time", ""), 12)
                   + _cut(title, 40))
            lines.append(row.rstrip())
            if verbose:
                if item.get("details_url"):
                    lines.append(f"      详情: {item['details_url']}")
                if item.get("download_url"):
                    lines.append(f"      下载: {item['download_url']}")
        if not r["results"]:
            lines.append(_pad(r["site"], 6) + f"  (无结果, total={r.get('total', 0)})")

    # 汇总行
    lines.append("")
    lines.append(" | ".join(f"[{sites.get_site(r['site'])['name']}] {r['total']} 条"
                            for r in reports))
    for r in failed:
        lines.append(f"失败: {r['site']} ({r['error']})")
    return "\n".join(lines)


def render_json(reports: list, keyword: str) -> str:
    """JSON 输出(权威格式, 含全部字段与 URL)。"""
    out = {
        "keyword": keyword,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "total_results": sum(r["total"] for r in reports),
        "sites": [{k: r[k] for k in ("site", "site_name", "status", "error",
                                     "total", "results")} for r in reports],
    }
    return json.dumps(out, ensure_ascii=False, indent=2, default=str)
