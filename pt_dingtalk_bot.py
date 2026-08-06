#!/usr/bin/env python3
"""钉钉企业内部应用机器人 Stream 模式启动器(接收 @ 消息 → 搜索回复)。

用法:
  python pt_dingtalk_bot.py              # 常驻(WebSocket 长连接, 自动重连)

前置: .env 必须配置 DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET
(企业内部应用凭据); 主动推送走 DINGTALK_WEBHOOK(见 pt_checkin.py --notify)。
"""

import argparse
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from common import dingtalk_bot, env


def main() -> int:
    env.load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    p = argparse.ArgumentParser(description="钉钉 stream 机器人(PT 搜索回复)")
    p.add_argument("--client-id", default="", help="覆盖 .env 的 DINGTALK_CLIENT_ID")
    p.add_argument("--client-secret", default="", help="覆盖 .env 的 DINGTALK_CLIENT_SECRET")
    args = p.parse_args()

    client_id = args.client_id or env.get("DINGTALK_CLIENT_ID")
    client_secret = args.client_secret or env.get("DINGTALK_CLIENT_SECRET")
    if not client_id or not client_secret:
        print("✗ 缺少 DINGTALK_CLIENT_ID / DINGTALK_CLIENT_SECRET"
              " (见 .env, 企业内部应用凭据)", file=sys.stderr)
        return 1

    try:
        return dingtalk_bot.start_bot(client_id, client_secret)
    except KeyboardInterrupt:
        print("\n已停止")
        return 0
    except Exception as e:
        print(f"✗ 启动失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
