#!/usr/bin/env python3
"""PT 四站统一搜索入口(azusa.wiki / tjupt.org / u2.dmhy.org / pterclub.net)。

用法:
  python pt_search.py "汉化"                      # 全站搜索(默认 4 站)
  python pt_search.py "汉化" --site azusa,tjupt   # 指定站点站内搜索
  python pt_search.py "4K" --limit 30 --page 1    # 每站条数 / 页码
  python pt_search.py "4K" --json                 # JSON 输出(含全部 URL)
  python pt_search.py "4K" -v                     # 表格下打印详情/下载链接
  python pt_search.py --check                     # 只做登录前预检(不需关键词)
  python pt_search.py "4K" --proxy http://127.0.0.1:7890 --force-login

登录前检测:
  --check 预检各站: 网络可达性 → 剩余登录次数(≤2 输出警告不登录)→ 本地 cookie 登录态。
  搜索模式下各站适配器自带保护: azusa 剩余次数 ≤2 拒绝登录;dmhy/ptclub cookie 失效
  报错并提示刷新;tjupt 登录失败(异地登录保护)明确提示。

依赖: conda env `pt`(requests/bs4/lxml/dotenv),各站已有登录脚本与 cookie 文件。
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
for _p in (_ROOT,):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import checkin, config, env, sites, unified


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="PT 四站统一搜索(azusa / tjupt / dmhy / ptclub)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("keyword", nargs="?", default="", help="搜索关键词(--check 时不需要)")
    p.add_argument("--site", "-s", default="",
                   help="指定站点(逗号分隔, 如 azusa,tjupt; 默认全部 4 站)")
    p.add_argument("--check", action="store_true",
                   help="只做登录前预检(可达性 + 剩余次数 + 登录态), 不搜索")
    p.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    p.add_argument("--limit", "-n", type=int, default=20, help="每站最多返回条数 (默认 20)")
    p.add_argument("--page", "-p", type=int, default=0, help="页码 (默认 0 = 第 1 页)")
    p.add_argument("--incldead", type=int, choices=[0, 1, 2], default=0,
                   help="种子状态: 0=全部, 1=活种, 2=断种 (azusa/tjupt)")
    p.add_argument("--proxy", default="", help="代理覆盖, 如 http://127.0.0.1:7890 "
                                               "(默认读 .env; tjupt 恒直连)")
    p.add_argument("--force-login", "-f", action="store_true",
                   help="本地 cookie 有效也强制重新登录(有风控风险, 勿用于定时任务)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="表格输出下打印详情/下载链接")
    p.add_argument("--timeout", type=int, default=None,
                   help="HTTP 超时秒数 (默认读 .env HTTP_TIMEOUT, 缺省 30)")
    return p.parse_args()


def main() -> int:
    env.load_env()
    args = parse_args()
    if args.timeout is None:
        args.timeout = config.get_int("HTTP_TIMEOUT", 30)

    keys = [k.strip() for k in args.site.split(",") if k.strip()] or sites.site_keys()
    for k in keys:
        if k not in sites.site_keys():
            print(f"✗ 未知站点: {k} (可用: {', '.join(sites.site_keys())})", file=sys.stderr)
            return 1

    # --check: 只做登录前预检
    if args.check:
        prechecks = sites.precheck_all(args.timeout)
        print(checkin.render_precheck(prechecks, keys))
        warned = [k for k in keys if prechecks[k]["warning"] or not prechecks[k]["reachable"]]
        return 1 if warned else 0

    if not args.keyword:
        print("✗ 需要搜索关键词(或使用 --check 只做预检)", file=sys.stderr)
        return 1

    # 全站/指定站搜索
    reports = unified.search_all(
        args.keyword, keys=keys,
        limit=args.limit, page=args.page, incldead=args.incldead,
        proxy=args.proxy, force_login=args.force_login,
        timeout=args.timeout,
    )

    if args.json:
        print(unified.render_json(reports, args.keyword))
    else:
        print(unified.render_table(reports, args.keyword, verbose=args.verbose))

    # 退出码: 全部成功 0; 有失败/无结果 1
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
