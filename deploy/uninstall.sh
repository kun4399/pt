#!/usr/bin/env bash
# ============================================================
# PT 站 systemd 服务卸载脚本(install.sh 的对应卸载)
#
# 用法(普通用户运行, 不要用 sudo):
#   ./deploy/uninstall.sh          # 卸载 systemd 服务(保留配置与数据)
#   ./deploy/uninstall.sh --purge  # 额外删除日志/cookie/油猴副本/frp 穿透
#   ./deploy/uninstall.sh --dry-run# 只预览要执行的命令, 不执行
#   ./deploy/uninstall.sh --help   # 帮助
#
# sudo 说明:
#   - **用普通用户运行本脚本**(如 kun), 不要 `sudo ./uninstall.sh`
#     - 脚本内部仅在需要时调用 sudo(停用 systemd 单元、重启 frpc),
#       会交互提示输入密码
#   - 默认只停用并删除 systemd 单元(pt-checkin.timer / pt-checkin.service
#     / pt-cookie-server.service / pt-dingtalk-bot.service),
#     代码、.env、data/ 数据全部保留
#   - --purge 额外: 移除 frpc.toml 的 pt-cookie 穿透并重启 frpc、
#     删除三个日志文件、删除 data/cookies/ 与油猴已配置副本;
#     .env 凭据始终保留(需手动删除)
#   - 可重复执行(幂等)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"

PURGE=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --purge) PURGE=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --help|-h)
            sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "未知参数: $arg (支持 --purge / --dry-run / --help)" >&2; exit 1 ;;
    esac
done

say()  { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

run() {
    if [ "$DRY_RUN" = "1" ]; then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

cd "$PROJECT_ROOT"

say "PT 站 systemd 服务卸载"
echo "  项目目录: $PROJECT_ROOT"
echo "  运行用户: $(id -un)"
[ "$DRY_RUN" = "1" ] && echo "  模式: dry-run (仅预览)"
[ "$PURGE" = "1" ] && echo "  模式: purge (含日志/cookie/frp 穿透清理)"

# ---- 0. root 运行警告 ----
if [ "$(id -u)" = "0" ]; then
    warn "检测到以 root 运行! 建议用普通用户执行"
    warn "正确用法: ./deploy/uninstall.sh (不要 sudo)"
fi

# ---- 1. 前置检查 ----
say "检查前置条件"
command -v systemctl >/dev/null 2>&1 || fail "systemctl 不可用"
command -v sudo >/dev/null 2>&1 || fail "sudo 不可用(停用 systemd 单元需要)"
ok "前置检查通过"

# ---- 2. 停用并删除 systemd 单元(需要 sudo) ----
say "停用并删除 systemd 单元 (需要 sudo 密码)"
for unit in pt-checkin.timer pt-checkin.service pt-cookie-server.service pt-dingtalk-bot.service; do
    if systemctl list-unit-files 2>/dev/null | grep -q "^${unit} "; then
        run sudo systemctl stop "$unit" 2>/dev/null || true
        run sudo systemctl disable "$unit" 2>/dev/null || true
        run sudo rm -f "/etc/systemd/system/$unit"
        ok "已删除 $unit"
    else
        ok "$unit 未安装, 跳过"
    fi
done
run sudo systemctl daemon-reload
ok "daemon-reload 完成"

# ---- 3. --purge: 清理数据与 frp 穿透 ----
if [ "$PURGE" = "1" ]; then
    # 3.1 frpc.toml 移除 pt-cookie 穿透(幂等)并重启 frpc
    FRPC_TOML="${FRPC_TOML:-/home/kun/frp/frpc.toml}"
    if [ -f "$FRPC_TOML" ] && grep -q 'name = "pt-cookie"' "$FRPC_TOML"; then
        say "移除 frpc.toml 的 pt-cookie 穿透 (需要 sudo 密码重启 frpc)"
        if [ "$DRY_RUN" = "1" ]; then
            echo "  [dry-run] 从 $FRPC_TOML 删除 pt-cookie 穿透块"
        else
            awk '
                /^\[\[proxies\]\]/ { if (buf != "" && !skip) printf "%s", buf; buf = $0 ORS; skip = 0; next }
                { if (!skip) buf = buf $0 ORS; if ($0 ~ /name = "pt-cookie"/) skip = 1 }
                END { if (buf != "" && !skip) printf "%s", buf }
            ' "$FRPC_TOML" > "$FRPC_TOML.tmp" && mv "$FRPC_TOML.tmp" "$FRPC_TOML"
            ok "已移除 pt-cookie 穿透"
        fi
        run sudo systemctl restart frpc
        ok "frpc 已重启"
    else
        ok "frpc.toml 无 pt-cookie 穿透, 跳过"
    fi

    # 3.2 删除日志与 cookie 数据
    say "删除日志与 cookie 数据"
    for f in "$PROJECT_ROOT/data/checkin.log" "$PROJECT_ROOT/data/cookie-server.log" \
             "$PROJECT_ROOT/data/dingtalk-bot.log"; do
        if [ -f "$f" ]; then
            run rm -f "$f"
            ok "已删除 $f"
        fi
    done
    if [ -d "$PROJECT_ROOT/data/cookies" ]; then
        run rm -rf "$PROJECT_ROOT/data/cookies"
        ok "已删除 data/cookies/ (四站 cookie)"
    fi
    if [ -f "$PROJECT_ROOT/userscripts/pt-cookie-sender.configured.user.js" ]; then
        run rm -f "$PROJECT_ROOT/userscripts/pt-cookie-sender.configured.user.js"
        ok "已删除油猴已配置副本 (含 token)"
    fi
else
    say "非 purge 模式, 保留日志与 cookie 数据"
fi

# ---- 4. 完成 ----
say "卸载完成"
echo "  已保留: 代码、.env 凭据、data/ 数据(日志/cookie)"
if [ "$PURGE" = "1" ]; then
    echo "  已清理: 日志、data/cookies/、油猴副本、frpc.toml 穿透"
fi
echo ""
echo "  彻底清除凭据(可选): rm $ENV_FILE"
echo "  重新安装:   ./deploy/install.sh"
