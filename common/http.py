"""会话构造与登录态检查。

来源: make_session — 合并 azusapt/azusa_login.py create_session L51-65、
      dmhypt/login.py L85-94 与 dmhy.py L60-72(两份相同)、
      ptclub/pterclub.py L72-88 的 header 部分、tjupt/tjupt_login.py L17-25;
      is_logged_in — 合并三站同构检查(azusa L730-752 / dmhy L115-120 /
      ptclub L91-98),按 azusa 语义排序: 失败词 → 标题 → cookie → 成功词。
"""

import requests

from . import constants, search


def make_session(proxy: str = "", ua: str = constants.UA_CHROME_X11,
                 extra_headers: dict | None = None) -> requests.Session:
    """创建带默认 header 的 requests.Session。

    trust_env=False: 禁用 requests 对环境变量 HTTP_PROXY/HTTPS_PROXY 的
    隐式读取, 代理完全由调用方显式传入决定(根 .env 的全局代理
    只影响 dmhy 显式读取的站点, 不改变其他站的直连行为)。
    """
    s = requests.Session()
    s.trust_env = False
    s.headers.update({
        "User-Agent": ua,
        "Accept": constants.DEFAULT_ACCEPT,
        "Accept-Language": constants.DEFAULT_ACCEPT_LANG,
        "Accept-Encoding": constants.DEFAULT_ACCEPT_ENCODING,
    })
    if extra_headers:
        s.headers.update(extra_headers)
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def is_logged_in(session, url: str, *, fail_keywords=(), success_keywords=(),
                 cookie_names=(), title_excludes=(), timeout: int = 30) -> bool:
    """检查 session 登录态。

    判定顺序(与 azusa 原语义一致):
      1. 页面含任一失败关键词 → False(封禁/未登录)
      2. 有 title_excludes 且标题存在且不含排除词 → True
      3. 指定 cookie 名全部存在 → True
      4. 页面含任一成功关键词(忽略大小写)→ True
      5. 否则 False
    """
    try:
        r = session.get(url, timeout=timeout)
    except Exception:
        return False
    text = r.text
    if any(k in text for k in fail_keywords):
        return False
    title = search.extract_title(text)
    if title_excludes and title and not any(x in title for x in title_excludes):
        return True
    if cookie_names and all(c in [c.name for c in session.cookies] for c in cookie_names):
        return True
    if success_keywords and any(k in text.lower() for k in success_keywords):
        return True
    return False
