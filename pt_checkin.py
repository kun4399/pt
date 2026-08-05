#!/usr/bin/env python3
"""PT 四站统一签到入口(azusa.wiki / tjupt.org / u2.dmhy.org / pterclub.net)。

用法:
  python pt_checkin.py                       # 四站自动签到(默认全部)
  python pt_checkin.py --site tjupt,dmhy     # 指定站点(逗号分隔)
  python pt_checkin.py --json                # JSON 输出(权威格式)
  python pt_checkin.py --check               # 只做登录前预检, 不签到
  python pt_checkin.py -v                    # 表格下打印 detail

站点签到机制:
  azusa  签到系统已官方下线 → 自动跳过 (attendance.php 无表单, "签到成功"为反爬诱饵)
  tjupt  海报 OCR 签到 (attendance.php, 直连; cookie-first, 失效自动登录)
  dmhy   作品名验证码签到 (showup.php, cookie 模式; 失效提示先运行 login.py)
  ptclub 签到得猫粮 (GET attendance-ajax.php, cookie 模式)

退出码: 全部正常(成功/已签到/跳过)= 0; 任一失败(登录失败/cookie 失效/网络错误)= 1。
可用于 crontab 定时签到: 退出码 0 视为当日签到完成。
"""

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from common import checkin, config, env, notify, sites


def parse_args():
    p = argparse.ArgumentParser(
        description="PT 四站统一签到(azusa / tjupt / dmhy / ptclub)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--site", "-s", default="",
                   help="指定站点(逗号分隔, 如 tjupt,dmhy; 默认全部 4 站)")
    p.add_argument("--check", action="store_true",
                   help="只做登录前预检(可达性 + 剩余次数 + 登录态), 不签到")
    p.add_argument("--json", "-j", action="store_true", help="JSON 输出")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="表格输出下打印 detail")
    p.add_argument("--proxy", default="", help="代理覆盖, 如 http://127.0.0.1:7890 "
                                               "(默认读 .env; tjupt 恒直连)")
    p.add_argument("--timeout", type=int, default=None,
                   help="HTTP 超时秒数 (默认读 .env HTTP_TIMEOUT, 缺省 30)")
    p.add_argument("--notify", action="store_true",
                   help="签到后: 失败的站重试(最多 3 次)仍失败, 或 cookie 失效, "
                        "通过钉钉机器人通知(需 .env 配置 DINGTALK_WEBHOOK/SECRET)")
    p.add_argument("--notify-test", action="store_true",
                   help="发送一条钉钉测试消息验证加签配置, 不签到")
    return p.parse_args()


def main() -> int:
    env.load_env()
    args = parse_args()
    if args.timeout is None:
        args.timeout = config.get_int("HTTP_TIMEOUT", 30)

    # --notify-test: 只发测试消息验证加签, 不签到
    if args.notify_test:
        ok = notify.send_dingtalk(
            f"【PT 签到通知测试】钉钉机器人加签配置验证成功 ({env.get('TJPT_USERNAME') or ''})")
        print(f"钉钉通知: {'已发送' if ok else '发送失败'}")
        return 0 if ok else 1

    keys = [k.strip() for k in args.site.split(",") if k.strip()] or sites.site_keys()
    for k in keys:
        if k not in sites.site_keys():
            print(f"✗ 未知站点: {k} (可用: {', '.join(sites.site_keys())})", file=sys.stderr)
            return 1

    # 登录前预检(可达性 → 剩余次数 → 本地 cookie 登录态)
    prechecks = sites.precheck_all(args.timeout)

    if args.check:
        print(checkin.render_precheck(prechecks, keys))
        warned = [k for k in keys if prechecks[k]["warning"] or not prechecks[k]["reachable"]]
        return 1 if warned else 0

    # 逐站签到(单站失败不中断其他站)
    reports = []
    for k in keys:
        kw = {"proxy": args.proxy, "timeout": args.timeout}
        if args.notify and prechecks[k].get("warning"):
            # 剩余次数 ≤2: 风控保护, 不重试(重试可能消耗登录次数)
            reports.append(checkin.checkin_site(k, **kw))
        elif args.notify:
            r, _n = checkin.checkin_with_retry(k, **kw)
            reports.append(r)
        else:
            reports.append(checkin.checkin_site(k, **kw))

    if args.json:
        print(checkin.render_json(reports, prechecks))
    else:
        print(checkin.render_table(reports, prechecks, verbose=args.verbose))

    # --notify: 失败的站(含重试后仍失败/cookie 失效)→ 钉钉通知
    if args.notify:
        failures = [r for r in reports if not r["ok"]]
        if failures:
            text = checkin.build_failure_text(failures, total=len(reports))
            sent = notify.send_dingtalk(text)
            print(f"钉钉通知: {'已发送' if sent else '发送失败'} ({len(failures)} 站失败)")
        # 全部成功: 不发通知, 保持日志干净

    # 退出码: 全部 ok(成功/已签到/跳过)为 0, 方便 cron 判断
    return 0 if all(r["ok"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
