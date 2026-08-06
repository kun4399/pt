"""钉钉企业内部应用机器人 Stream 模式(双向)。

- 主动推送: 走 DINGTALK_WEBHOOK(见 notify.py, 未开加签时无需签名)
- 接收消息: WebSocket 长连接(dingtalk-stream SDK 自动处理鉴权/心跳/重连),
  群聊中 @ 机器人或单聊发消息 → 以消息文本为关键词搜索四站 PT 资源 →
  按钉钉 markdown 回复(标题/列表/链接, 钉钉不支持表格)

依赖: pip install dingtalk-stream
配置(.env): DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET(stream 鉴权),
            BOT_REPLY_LIMIT(回复每站条数, 默认 5)
"""

import logging
import re
from urllib.parse import quote

import dingtalk_stream
from dingtalk_stream import AckMessage, ChatbotMessage

from . import config, env, sites, unified

log = logging.getLogger("pt.common.dingtalk_bot")


def _download_link(site: str, download_url: str) -> str:
    """下载链接 → 代理下载端点(服务器用本地 cookie 拉种子, 浏览器免登录/免代理)。

    未配置 COOKIE_DOWNLOAD_TOKEN 时退回原始下载链接(需要浏览器登录)。
    """
    token = env.get("COOKIE_DOWNLOAD_TOKEN")
    if not token or not download_url:
        return download_url
    frp_ip = config.get_str("FRP_PUBLIC_IP", "")
    port = config.get_int("COOKIE_SERVER_PORT", 8766)
    if not frp_ip:
        return download_url
    return (f"http://{frp_ip}:{port}/api/download"
            f"?site={site}&url={quote(download_url, safe='')}&token={token}")


def _clean_keyword(text: str, bot_name: str = "") -> str:
    """清洗消息文本: 去掉 "@机器人昵称" 前缀与多余空白。

    bot_name 为机器人昵称(可能含空格, 如 "pt 助手"), 配置后精确匹配;
    未配置时兜底去掉开头所有 "@提及" token(昵称含空格时会残留昵称其余部分,
    建议在 .env 配置 DINGTALK_BOT_NAME)。
    """
    text = (text or "").strip()
    if text.startswith("@"):
        if bot_name:
            text = re.sub(rf"^@\s*{re.escape(bot_name)}\s*", "", text, count=1)
        else:
            text = re.sub(r"^(?:@\S+\s*)+", "", text)
    return text.strip()


def _cut(s, width) -> str:
    """按显示宽度截断(中文算 2), 超长加 "..."。"""
    s = str(s)
    w = 0
    out = ""
    for c in s:
        cw = 2 if ord(c) > 127 else 1
        if w + cw > width:
            break
        out += c
        w += cw
    return out + "..." if w != sum(2 if ord(c) > 127 else 1 for c in s) else s


# 钉钉 markdown 消息上限 20000 字符, 留安全余量
_MAX_MD_CHARS = 18000


def build_site_block(site_name: str, results: list, limit: int = 4) -> str:
    """单站结果块 → 卡片片段(每条 3 行: 标题链接 / 信息行 / 下载)。

    手机端友好: 无表格无 emoji, 标题本身可点击跳详情页, 下载链接独立一行。
    """
    results = sorted(results, key=lambda x: x.get("seeders") or 0,
                     reverse=True)[:limit]
    if not results:
        return f"**{site_name}**\n   无结果\n\n"

    parts = [f"**{site_name}**"]
    for i, item in enumerate(results, 1):
        title = item.get("title", "")
        if item.get("promotion"):
            title = f"[{item['promotion']}] {title}"
        # 第 1 行: 标题(可点击 → 详情页; 标题内方括号需转义避免破坏链接语法)
        if item.get("details_url"):
            title_md = title.replace("[", "\\[").replace("]", "\\]")
            parts.append(f"{i}. [{title_md}]({item['details_url']})")
        else:
            parts.append(f"{i}. {title}")
        # 第 2 行: 信息(大小 · 做种 · 完成)
        info = " · ".join(filter(None, [
            item.get("size", ""),
            f"做种 {item.get('seeders') or 0}",
            f"完成 {item.get('completed') or 0}",
        ]))
        parts.append(f"   {info}")
        # 第 3 行: 下载
        if item.get("download_url"):
            parts.append(f"   [下载]({_download_link(item.get('site', ''), item['download_url'])})")
    return "\n".join(parts) + "\n\n"


class PtSearchBotHandler(dingtalk_stream.ChatbotHandler):
    """@机器人 → 关键词 → 四站搜索 → markdown 回复。"""

    async def process(self, callback):
        msg = ChatbotMessage.from_dict(callback.data)
        bot_name = config.get_str("DINGTALK_BOT_NAME")
        keyword = _clean_keyword(msg.text.content if msg.text else "", bot_name)
        log.info("收到消息: sender=%s conv=%s keyword=%r",
                 getattr(msg, "senderNick", "?"),
                 getattr(msg, "conversationTitle", "?"),
                 keyword)

        if not keyword:
            self.reply_text("请输入搜索关键词, 例如: @机器人 4K", msg)
            return AckMessage.STATUS_OK, "OK"

        # 1. 立即发送"搜索中"流式互动卡片(即时反馈, 同一张卡片原地更新)
        card = self.ai_markdown_card_start(msg, title=f"PT 搜索: {keyword}")
        card.ai_streaming("搜索中...\n\n", append=True)

        import time
        limit = config.get_int("BOT_REPLY_LIMIT", 4)
        timeout = config.get_int("HTTP_TIMEOUT", 30)
        start = time.time()
        ok_count = 0
        total = 0
        try:
            # 2. 逐站搜索: 先推进度, 结果出来实时追加(流式仅用于进度与结果)
            for site_key in sites.site_keys():
                card.ai_streaming(
                    f"正在搜索 {sites.get_site(site_key)['name']}...\n", append=True)
                r = unified.search_site(site_key, keyword, limit=limit * 6, timeout=timeout)
                if r["ok"]:
                    ok_count += 1
                    total += r["total"]
                    card.ai_streaming(
                        build_site_block(r["site_name"], r["results"], limit=limit),
                        append=True)
                else:
                    card.ai_streaming(
                        f"**{r['site_name']}** 失败: {r.get('error') or r.get('status', '')}\n\n",
                        append=True)

            # 3. 完成态(含耗时)
            elapsed = int(time.time() - start)
            if total == 0 and ok_count == 0:
                card.ai_finish("四站均搜索失败, 请稍后重试", tips="搜索失败")
            elif total == 0:
                card.ai_finish(f"未找到 \"{keyword}\" 相关资源", tips="无结果")
            else:
                tips = f"共 {total} 条 · {ok_count} 站成功 · 耗时 {elapsed}s"
                if ok_count < len(sites.site_keys()):
                    tips += " · 部分站失败"
                card.ai_finish(tips=tips)
            log.info("流式卡片已完成 keyword=%r (total=%d, ok=%d, %ds)",
                     keyword, total, ok_count, elapsed)
        except Exception as e:
            log.warning("搜索处理失败: %s: %s", type(e).__name__, e)
            card.ai_fail()
            self.reply_text(f"搜索失败: {e}", msg)

        return AckMessage.STATUS_OK, "OK"


def start_bot(client_id: str, client_secret: str) -> int:
    """启动 stream 机器人(阻塞, 自动重连)。client_id/secret 为空抛 ValueError。"""
    if not client_id or not client_secret:
        raise ValueError("缺少 DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET (.env)")
    credential = dingtalk_stream.Credential(client_id, client_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(ChatbotMessage.TOPIC, PtSearchBotHandler())
    log.info("钉钉 stream 机器人启动 (client_id=%s...)", client_id[:10])
    client.start_forever()
    return 0
