#!/usr/bin/env python3
"""浏览器油猴 cookie 接收服务启动器(HTTP, 零第三方依赖)。

用法:
  python pt_cookie_server.py                     # 127.0.0.1:8766 (默认)
  python pt_cookie_server.py --host 0.0.0.0 --port 9000

前置: .env 必须配置 COOKIE_SERVER_TOKEN(公网经 frp 暴露的鉴权底线,
deploy/install.sh 会自动生成; 未配置时本服务拒绝启动)。
"""

import argparse
import logging
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from common import cookie_server, env


def main() -> int:
    env.load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    p = argparse.ArgumentParser(description="PT cookie 接收服务(油猴脚本 → 本地保存)")
    p.add_argument("--host", default=cookie_server.DEFAULT_HOST,
                   help=f"监听地址 (默认 {cookie_server.DEFAULT_HOST}, 由 frp 转发)")
    p.add_argument("--port", type=int, default=cookie_server.DEFAULT_PORT,
                   help=f"监听端口 (默认 {cookie_server.DEFAULT_PORT})")
    args = p.parse_args()

    try:
        token = cookie_server.require_token()
    except RuntimeError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1

    server = cookie_server.make_server(args.host, args.port, token)
    print(f"cookie server listening on http://{args.host}:{args.port} (token 已配置)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
