"""四站统一签到适配器 + 输出渲染(供 pt_checkin.py 使用)。

与 common/unified.py 同构: 站点逻辑留在站点模块, 本模块只做统一适配与渲染。
- checkin_site(): 单站签到, 复用各站现有签到实现
  azusa 签到已官方下线 → 零请求直接报 skipped;
  tjupt 走 tjupt_sign.sign(海报 OCR, cookie-first);
  dmhy 走 dmhy.checkin(cookie 模式, 不自动登录);
  ptclub 走 pterclub.attendance_checkin(GET attendance-ajax.php)。
- checkin_all(): 默认全部站点, 单站失败不拖垮整体。
- render_precheck(): 登录前预检表格(从 pt_search.py 迁入, 输出逐字一致)。
- render_table()/render_json(): 统一签到输出。
"""

import importlib
import json
import logging
from datetime import datetime, timezone

from . import sites
from .unified import _load_module, _pad, _dw, _cut

STATUS_OK = "ok"                    # 签到成功
STATUS_ALREADY = "already"          # 今日已签到
STATUS_SKIPPED = "skipped"          # azusa 签到官方下线, 跳过
STATUS_LOGIN_FAILED = "login_failed"
STATUS_COOKIE_INVALID = "cookie_invalid"
STATUS_NETWORK_ERROR = "network_error"
STATUS_FAILED = "failed"

STATUS_LABEL = {
    STATUS_OK: "成功", STATUS_ALREADY: "已签到", STATUS_SKIPPED: "跳过",
    STATUS_LOGIN_FAILED: "登录失败", STATUS_COOKIE_INVALID: "cookie 失效",
    STATUS_NETWORK_ERROR: "网络错误", STATUS_FAILED: "失败",
}


def _fail(site_key, status, message, detail="") -> dict:
    return {"site": site_key, "site_name": sites.get_site(site_key)["name"],
            "ok": False, "status": status, "message": message, "detail": detail}


def _ok(site_key, status, message, detail="") -> dict:
    return {"site": site_key, "site_name": sites.get_site(site_key)["name"],
            "ok": True, "status": status, "message": message, "detail": detail}


# ---------------------------------------------------------------------------
# 单站签到
# ---------------------------------------------------------------------------

def checkin_site(site_key: str, *, proxy: str = "", force_login: bool = False,
                 timeout: int = 30) -> dict:
    """统一单站签到。返回 {site, site_name, ok, status, message, detail}。

    ok: True = 流程正常完成(成功/已签到/跳过);False = 需要人工处理。
    status ∈ {ok, already, skipped, login_failed, cookie_invalid, network_error, failed}
    """
    if site_key not in sites.site_keys():
        return _fail(site_key, STATUS_NETWORK_ERROR, f"未知站点: {site_key}")
    try:
        if site_key == "azusa":
            return _azusa_checkin()
        if site_key == "tjupt":
            return _tjupt_checkin(proxy, force_login, timeout)
        if site_key == "dmhy":
            return _dmhy_checkin(proxy, timeout)
        if site_key == "ptclub":
            return _ptclub_checkin(proxy, timeout)
    except Exception as e:
        return _fail(site_key, STATUS_NETWORK_ERROR, f"{type(e).__name__}: {e}")
    return _fail(site_key, STATUS_NETWORK_ERROR, "未知站点")


def _azusa_checkin() -> dict:
    """azusa 签到已官方下线(attendance.php 无表单; showup/bonus 404;
    页面"签到成功"为反爬诱饵, 不可作判定), 零请求直接跳过。"""
    return _ok("azusa", STATUS_SKIPPED,
               "签到功能已官方下线 (请前往任务系统了解每日任务)",
               "attendance.php 无签到表单; 页面\"签到成功…请忽略\"为反爬诱饵文本")


def _tjupt_checkin(proxy, force_login, timeout):
    from common import cookies, http
    mod_login = _load_module("tjupt")
    mod_sign = importlib.import_module("sites.tjupt.tjupt_sign")
    session = http.make_session()  # tjupt 永远直连

    # cookie-first
    if not force_login:
        p = sites.cookie_path("tjupt")
        if p and p.exists():
            cookies.load_key_value(session, p, domain="tjupt.org")
            if sites.login_check("tjupt", session, timeout):
                return _map_tjupt_sign(mod_sign.sign(session=session, verbose=False))

    login_session = mod_login.login(verbose=False)
    if login_session is None:
        return _fail("tjupt", STATUS_LOGIN_FAILED,
                     "登录失败 (可能触发异地登录保护, 需在常用网络/IP 下登录)")
    session = login_session
    if not sites.login_check("tjupt", session, timeout):
        return _fail("tjupt", STATUS_LOGIN_FAILED, "登录后验证未通过 (异地登录保护?)")
    return _map_tjupt_sign(mod_sign.sign(session=session, verbose=False))


def _map_tjupt_sign(r: dict) -> dict:
    if r["success"] and r["already"]:
        return _ok("tjupt", STATUS_ALREADY, r["message"], f"attempts={r['attempts']}")
    if r["success"]:
        return _ok("tjupt", STATUS_OK, r["message"], f"attempts={r['attempts']}")
    return _fail("tjupt", STATUS_FAILED, r["message"], r.get("detail", ""))


def _dmhy_checkin(proxy, timeout):
    mod = _load_module("dmhy")
    session = mod._load_session(proxy)
    if session is None or not sites.login_check("dmhy", session, timeout):
        return _fail("dmhy", STATUS_COOKIE_INVALID,
                     "cookies.pkl 缺失或已过期, 请先运行 sites/dmhypt/login.py")
    # 独立 logger(默认 WARNING), 抑制 checkin() 内部 log.info 污染统一输出
    log = logging.getLogger("pt.checkin.dmhy")
    r = mod.checkin(session, timeout=timeout, log=log)
    if not r["success"]:
        return _fail("dmhy", STATUS_FAILED, r.get("message", "签到失败"))
    if r.get("already"):
        return _ok("dmhy", STATUS_ALREADY, r.get("message", "今日已签到"))
    msg = r.get("message", "签到成功")
    if r.get("ucoin") is not None:
        msg += f" (+{r['ucoin']} UCoin)"
    return _ok("dmhy", STATUS_OK, msg)


def _ptclub_checkin(proxy, timeout):
    mod = _load_module("ptclub")
    # 先 check_login, 避免无效 cookie 下签到接口返回歧义
    if not mod.check_login(proxy):
        return _fail("ptclub", STATUS_COOKIE_INVALID,
                     "cookies.json 缺失或已过期, 请用浏览器重新导出")
    r = mod.attendance_checkin(proxy=proxy)
    if r["already"]:
        return _ok("ptclub", STATUS_ALREADY, r["message"])
    if r["success"]:
        return _ok("ptclub", STATUS_OK, r["message"])
    return _fail("ptclub", STATUS_FAILED, r["message"])


# ---------------------------------------------------------------------------
# 失败重试与通知文案 (pt_checkin.py --notify 用)
# ---------------------------------------------------------------------------

# 可重试状态: 登录失败/签到失败/网络错误(cookie_invalid 不重试——
# ptclub/dmhy 无自动登录通道, 重试无意义, 直接通知用户手动处理)
RETRYABLE_STATUSES = (STATUS_LOGIN_FAILED, STATUS_FAILED, STATUS_NETWORK_ERROR)


def checkin_with_retry(site_key: str, *, max_retries: int = 3, interval: float = 30.0,
                       **kw) -> tuple:
    """带重试的单站签到。返回 (最终 report, 总尝试次数 attempts)。

    初试失败且 status ∈ RETRYABLE_STATUSES 时重试, 最多 max_retries 次
    (总尝试 ≤ max_retries+1), 每次 sleep(interval) 后重新调 checkin_site()。
    重试后仍失败时 report["detail"] 追加 "(重试 N 次)" 标注。
    注意: 预检剩余次数 ≤2 的站不应调用本函数(风控保护, 见 pt_checkin.py 编排)。
    """
    import time
    r = checkin_site(site_key, **kw)
    attempts = 1
    while (not r["ok"] and r["status"] in RETRYABLE_STATUSES
           and attempts <= max_retries):
        time.sleep(interval)
        r = checkin_site(site_key, **kw)
        attempts += 1
    if attempts > 1 and not r["ok"]:
        r = dict(r)
        r["detail"] = (f"{r.get('detail', '')} (重试 {attempts - 1} 次)").strip()
    return r, attempts


def build_failure_text(failures: list, *, total: int, now=None) -> str:
    """失败站点列表 → 钉钉文本消息。cookie_invalid 附"需手动更新 cookie"提示。"""
    from datetime import datetime as _dt
    now = now or _dt.now()
    lines = [f"【PT 签到失败】{now:%Y-%m-%d %H:%M}",
             f"共 {total} 站, 失败 {len(failures)} 站", ""]
    for r in failures:
        lines.append(f"■ {r['site_name']} ({r['site']})")
        lines.append(f"  状态: {STATUS_LABEL.get(r['status'], r['status'])}")
        if r.get("message"):
            lines.append(f"  原因: {r['message']}")
        if r.get("detail"):
            lines.append(f"  细节: {r['detail']}")
        if r["status"] == STATUS_COOKIE_INVALID:
            lines.append("  → 需手动更新 cookie")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# 全站签到
# ---------------------------------------------------------------------------

def checkin_all(keys: list | None = None, **kw) -> list:
    """默认全部站点; 单站异常独立上报, 不中断其他站。返回 [report, ...]。"""
    keys = keys or sites.site_keys()
    return [checkin_site(k, **kw) for k in keys]


# ---------------------------------------------------------------------------
# 渲染
# ---------------------------------------------------------------------------

def render_precheck(prechecks: dict, keys: list) -> str:
    """登录前预检表格: 可达性 / HTTP / 剩余次数 / 状态。(自 pt_search.py 迁入)"""
    lines = []
    lines.append(f"=== PT 站登录前预检 ({datetime.now():%Y-%m-%d %H:%M}) ===")
    headers = [("站点", 8), ("可达", 5), ("HTTP", 5), ("剩余次数", 9), ("状态", 0)]
    head = "".join(_pad(h, w) for h, w in headers[:-1]) + headers[-1][0]
    lines.append(head)
    lines.append("-" * min(80, _dw(head)))

    for key in keys:
        r = prechecks[key]
        reachable = "OK" if r["reachable"] else "✗"
        status_http = str(r["http_status"]) if r["http_status"] else "-"
        if r["attempts_remaining"] is None:
            attempts = "N/A"
        elif r["attempts_total"]:
            attempts = f"{r['attempts_remaining']}/{r['attempts_total']}"
        else:
            attempts = str(r["attempts_remaining"])

        if not r["reachable"]:
            status = f"不可达 ({r['error']})"
        elif r["blocked"]:
            status = f"[封禁] {r['detail']}"
        elif r["warning"]:
            status = f"[警告] 仅剩 {r['attempts_remaining']} 次, 不执行登录"
        elif r["logged_in"] is True:
            status = "已登录 (本地 cookie 有效)"
        elif r["logged_in"] is False:
            status = "未登录 (cookie 失效)"
        elif key == "tjupt":
            status = "ok (无次数机制; 异地登录保护无法预检)"
        else:
            status = "ok"

        lines.append(_pad(key, 8) + _pad(reachable, 5)
                     + _pad(status_http, 5) + _pad(attempts, 9)
                     + status)
    return "\n".join(lines)


def render_table(reports: list, prechecks: dict | None = None,
                 verbose: bool = False) -> str:
    """统一签到表格输出。prechecks 非空时先打印预检表(与 --check 同款)。"""
    lines = []
    if prechecks:
        lines.append(render_precheck(prechecks, [r["site"] for r in reports]))
        lines.append("")
    lines.append(f"=== PT 站自动签到 ({datetime.now():%Y-%m-%d %H:%M}) ===")

    headers = [("站点", 8), ("状态", 10), ("结果", 0)]
    head = "".join(_pad(h, w) for h, w in headers[:-1]) + headers[-1][0]
    lines.append(head)
    lines.append("-" * min(80, _dw(head)))

    for r in reports:
        label = STATUS_LABEL.get(r["status"], r["status"])
        row = _pad(r["site"], 8) + _pad(label, 10) + r["message"]
        lines.append(row)
        if verbose and r.get("detail"):
            lines.append(f"        {r['detail']}")
    return "\n".join(lines)


def render_json(reports: list, prechecks: dict | None = None) -> str:
    """JSON 输出(权威格式)。"""
    out = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "sites": [{k: r[k] for k in ("site", "site_name", "status", "ok",
                                     "message", "detail")} for r in reports],
    }
    if prechecks:
        out["precheck"] = {
            k: {kk: vv for kk, vv in v.items() if kk != "detail"}
            for k, v in prechecks.items()
        }
    return json.dumps(out, ensure_ascii=False, indent=2, default=str)
