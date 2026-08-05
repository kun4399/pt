"""钉钉机器人通知(自定义机器人, "加签"安全设置)。

加签算法(钉钉官方):
  timestamp = 毫秒时间戳; string_to_sign = f"{timestamp}\\n{secret}"
  sign = urlencode(base64(HmacSHA256(key=secret, msg=string_to_sign)))
  请求 URL 追加 &timestamp={ts}&sign={sign}, POST JSON {"msgtype":"text","text":{"content":...}}

webhook/secret 优先用显式参数,缺省读 .env 的 DINGTALK_WEBHOOK / DINGTALK_SECRET;
任一为空则跳过(不通知)。发送使用 http.make_session()(trust_env=False 直连,
oapi.dingtalk.com 为国内域名, TUN 规则 GEOIP CN → DIRECT)。任何失败静默
(logging.warning), 不抛异常, 不影响签到主流程。
"""

import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import quote_plus

from . import env, http

log = logging.getLogger("pt.common.notify")

TIMEOUT = 10


def _sign(secret: str, timestamp_ms: str) -> str:
    """钉钉加签: sign = urlencode(base64(HmacSHA256(key=secret, msg=f"{ts}\\n{secret}")))。"""
    string_to_sign = f"{timestamp_ms}\n{secret}"
    digest = hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    return quote_plus(base64.b64encode(digest))


def send_dingtalk(text: str, webhook: str = "", secret: str = "") -> bool:
    """发送钉钉文本消息。返回是否发送成功(True = 钉钉已接收, errcode==0)。

    webhook/secret 为空时读 .env 的 DINGTALK_WEBHOOK / DINGTALK_SECRET;
    两者任一为空 → 提示"未配置, 跳过"并返回 False(不抛异常)。
    发送/HTTP/JSON/errcode 任一异常 → log.warning(截断响应体) 返回 False。
    """
    if not webhook:
        webhook = env.get("DINGTALK_WEBHOOK")
    if not secret:
        secret = env.get("DINGTALK_SECRET")
    if not webhook or not secret:
        log.info("钉钉通知未配置 (DINGTALK_WEBHOOK/DINGTALK_SECRET), 跳过")
        return False

    timestamp_ms = str(round(time.time() * 1000))
    sep = "&" if "?" in webhook else "?"
    url = f"{webhook}{sep}timestamp={timestamp_ms}&sign={_sign(secret, timestamp_ms)}"

    session = http.make_session()
    try:
        resp = session.post(url, json={"msgtype": "text", "text": {"content": text}},
                            timeout=TIMEOUT)
        data = resp.json()
        if resp.status_code == 200 and data.get("errcode") == 0:
            log.info("钉钉通知已发送")
            return True
        log.warning("钉钉通知发送失败: errcode=%s errmsg=%s",
                    data.get("errcode"), str(data.get("errmsg", ""))[:120])
    except Exception as e:
        log.warning("钉钉通知发送异常: %s: %s", type(e).__name__, str(e)[:120])
    return False
