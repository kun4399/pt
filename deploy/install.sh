#!/usr/bin/env bash
# ============================================================
# PT 站 systemd 服务一键安装脚本
#
# 用法(普通用户运行, 不要用 sudo):
#   ./deploy/install.sh             # 一键安装(含钉钉测试消息)
#   ./deploy/install.sh --no-test   # 跳过钉钉测试消息
#   ./deploy/install.sh --dry-run   # 只预览要执行的命令, 不执行
#   ./deploy/install.sh --help      # 帮助
#
# sudo 说明:
#   - **用普通用户运行本脚本**(如 kun), 不要 `sudo ./install.sh`
#     - 脚本内部仅在需要时调用 sudo(安装 systemd 单元、重启 frpc),
#       会交互提示输入密码
#     - 若误用 sudo 运行, 服务 User 会被写成 root(脚本已用 SUDO_USER
#       自动纠正, 并给出警告)
#   - 安装内容: 每日签到定时器 + cookie 接收服务 + 钉钉机器人服务
#     (后两者按 .env 配置情况决定是否安装)
#
# 可重复执行(幂等): 重跑会覆盖单元、强制重启服务加载最新代码
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_ROOT/.env"
SERVICE="pt-checkin.service"
TIMER="pt-checkin.timer"
# conda env pt 的 python(可用环境变量 PYTHON 覆盖)
PYTHON="${PYTHON:-/home/kun/miniconda3/envs/pt/bin/python}"
# 服务 User/Group: 普通用户运行取当前用户; sudo 运行时取 SUDO_USER(原始用户)
SVC_USER="${SUDO_USER:-$(id -un)}"
SVC_GROUP="$(id -gn "$SVC_USER" 2>/dev/null || echo "$SVC_USER")"
LOG_FILE="$PROJECT_ROOT/data/checkin.log"

TEST_NOTIFY=1
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --no-test) TEST_NOTIFY=0 ;;
        --dry-run) DRY_RUN=1 ;;
        --help|-h)
            # 打印头部注释块(去掉 # 前缀)
            awk 'NR > 1 && /^#/ { print substr($0, 3) } NR > 1 && !/^#/ { exit }' "$0"
            exit 0 ;;
        *) echo "未知参数: $arg (支持 --no-test / --dry-run / --help)" >&2; exit 1 ;;
    esac
done

say()  { printf '\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m  ⚠ %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

# 实际执行或 dry-run 预览
run() {
    if [ "$DRY_RUN" = "1" ]; then
        printf '  [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

# 安装并启用 systemd 单元(强制 restart 确保加载最新代码)
install_unit() {
    local unit="$1"
    run sudo cp "$SCRIPT_DIR/$unit" "/etc/systemd/system/$unit"
    run sudo sed -i "s/^User=.*/User=$SVC_USER/; s/^Group=.*/Group=$SVC_GROUP/" "/etc/systemd/system/$unit"
    run sudo systemctl daemon-reload
    run sudo systemctl enable "$unit"
    run sudo systemctl restart "$unit" || true
}

cd "$PROJECT_ROOT"

say "PT 站 systemd 服务一键安装"
echo "  项目目录: $PROJECT_ROOT"
echo "  运行用户: $(id -un) (服务将以 $SVC_USER 运行)"
[ "$DRY_RUN" = "1" ] && echo "  模式: dry-run (仅预览)"

# ---- 0. root 运行警告 ----
if [ "$(id -u)" = "0" ]; then
    warn "检测到以 root 运行! 建议用普通用户执行(服务 User 已自动纠正为 $SVC_USER)"
    warn "正确用法: ./deploy/install.sh (不要 sudo)"
fi

# ---- 1. 前置检查 ----
say "检查前置条件"
[ -f "$PYTHON" ] || fail "未找到 conda python: $PYTHON (可用 PYTHON= 环境变量覆盖)"
[ -f "$SCRIPT_DIR/$SERVICE" ] || fail "缺少单元文件: deploy/$SERVICE"
[ -f "$SCRIPT_DIR/$TIMER" ] || fail "缺少单元文件: deploy/$TIMER"
command -v systemctl >/dev/null 2>&1 || fail "systemctl 不可用"
command -v sudo >/dev/null 2>&1 || fail "sudo 不可用(安装 systemd 单元需要)"
command -v openssl >/dev/null 2>&1 || warn "openssl 不可用(生成 token 将用 /dev/urandom 兜底)"
if ! "$PYTHON" -c "import dingtalk_stream" 2>/dev/null; then
    warn "dingtalk-stream 未安装(钉钉机器人依赖), 执行: $PYTHON -m pip install dingtalk-stream"
fi
ok "前置检查通过"

# ---- 2. 钉钉配置检查 ----
if grep -q "^DINGTALK_WEBHOOK=." "$ENV_FILE" 2>/dev/null; then
    ok "钉钉推送已配置 (DINGTALK_WEBHOOK)"
else
    warn ".env 未配置 DINGTALK_WEBHOOK → 签到失败时不会收到钉钉通知"
fi

# ---- 3. 钉钉测试消息(默认发送, 验证推送链路) ----
if [ "$TEST_NOTIFY" = "1" ]; then
    say "发送钉钉测试消息"
    run "$PYTHON" "$PROJECT_ROOT/pt_checkin.py" --notify-test
    ok "测试消息已发送, 请在钉钉确认收到"
else
    say "跳过钉钉测试消息 (--no-test)"
fi

# ---- 4. 预建日志文件(保持服务用户属主) ----
say "预建日志文件"
mkdir -p "$PROJECT_ROOT/data"
run touch "$LOG_FILE" "$PROJECT_ROOT/data/cookie-server.log" "$PROJECT_ROOT/data/dingtalk-bot.log"
ok "日志文件: data/{checkin,cookie-server,dingtalk-bot}.log"

# ---- 5. 每日签到定时器 ----
say "安装签到定时器 (每天 08:10, 需要 sudo 密码)"
install_unit "$SERVICE"
install_unit "$TIMER"
ok "已安装并启用 $TIMER (每天 08:10 自动四站签到, Persistent 开机补跑)"

# ---- 6. cookie 接收服务 ----
# 6.1 生成 token(未配置才生成, 幂等)
if grep -q "^COOKIE_SERVER_TOKEN=." "$ENV_FILE" 2>/dev/null; then
    COOKIE_TOKEN="$(grep '^COOKIE_SERVER_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2)"
else
    say "生成 COOKIE_SERVER_TOKEN (写入 .env)"
    COOKIE_TOKEN="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    printf '\n# ---- cookie 接收服务(油猴脚本 → 服务器, 公网暴露必须) ----\nCOOKIE_SERVER_TOKEN=%s\n' "$COOKIE_TOKEN" >> "$ENV_FILE"
    ok "已生成 COOKIE_SERVER_TOKEN"
fi

if ! grep -q "^COOKIE_DOWNLOAD_TOKEN=." "$ENV_FILE" 2>/dev/null; then
    say "生成 COOKIE_DOWNLOAD_TOKEN (写入 .env)"
    DL_TOKEN="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    printf 'COOKIE_DOWNLOAD_TOKEN=%s\n' "$DL_TOKEN" >> "$ENV_FILE"
    ok "已生成 COOKIE_DOWNLOAD_TOKEN"
fi

# 6.2 安装 pt-cookie-server.service(常驻, 强制重启加载最新代码)
say "安装 cookie 接收服务 (常驻监听 127.0.0.1:8766, 需要 sudo 密码)"
install_unit "pt-cookie-server.service"
ok "已安装并启用 pt-cookie-server.service (含种子代理下载端点)"

# 6.3 frpc.toml 追加 pt-cookie 穿透(幂等)并重启 frpc
FRPC_TOML="${FRPC_TOML:-/home/kun/frp/frpc.toml}"
if [ -f "$FRPC_TOML" ]; then
    if grep -q 'name = "pt-cookie"' "$FRPC_TOML"; then
        ok "frpc.toml 已含 pt-cookie 穿透"
    else
        say "追加 frp 穿透到 $FRPC_TOML (需要 sudo 密码重启 frpc)"
        cat >> "$FRPC_TOML" <<EOF

[[proxies]]
name = "pt-cookie"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8766
remotePort = 8766
EOF
        run sudo systemctl restart frpc
        ok "frp 穿透已添加并重启 frpc (公网入口见下方油猴配置)"
    fi
else
    warn "未找到 $FRPC_TOML, 跳过 frp 配置 (可稍后手动追加 pt-cookie 穿透)"
fi

# ---- 7. 钉钉 stream 机器人(常驻, @机器人搜索回复) ----
if grep -q "^DINGTALK_CLIENT_ID=." "$ENV_FILE" 2>/dev/null \
   && grep -q "^DINGTALK_CLIENT_SECRET=." "$ENV_FILE" 2>/dev/null; then
    say "安装钉钉 stream 机器人服务 (常驻, @机器人搜索回复, 需要 sudo 密码)"
    install_unit "pt-dingtalk-bot.service"
    ok "已安装并启用 pt-dingtalk-bot.service (日志: data/dingtalk-bot.log)"
else
    warn "未配置 DINGTALK_CLIENT_ID/SECRET, 跳过钉钉机器人服务 (可在 .env 补配后重跑 install.sh)"
fi

# ---- 8. 生成油猴脚本已配置副本(填好 SERVER_URL/TOKEN, 直接安装即可) ----
FRP_IP="$(grep '^FRP_PUBLIC_IP=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2)"
COOKIE_PORT="$(grep '^COOKIE_SERVER_PORT=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2)"
FRP_IP="${FRP_IP:-39.101.137.195}"
COOKIE_PORT="${COOKIE_PORT:-8766}"
SERVER_URL="http://${FRP_IP}:${COOKIE_PORT}/api/cookie"
US_TPL="$PROJECT_ROOT/userscripts/pt-cookie-sender.user.js"
US_DIST="$PROJECT_ROOT/userscripts/pt-cookie-sender.configured.user.js"
if [ -f "$US_TPL" ]; then
    say "生成油猴脚本已配置副本"
    sed "s|^const SERVER_URL = .*|const SERVER_URL = '${SERVER_URL}';|; \
         s|^const TOKEN = .*|const TOKEN = '${COOKIE_TOKEN}';|" "$US_TPL" > "$US_DIST"
    ok "已生成: userscripts/pt-cookie-sender.configured.user.js (浏览器直接安装此文件)"
fi

# ---- 9. 完成 ----
say "安装完成"
echo ""
echo "  服务状态(全部):"
echo "    systemctl list-timers --all | grep pt-checkin   # 签到定时器"
echo "    systemctl status pt-cookie-server.service       # cookie 接收 + 种子代理下载"
echo "    systemctl status pt-dingtalk-bot.service        # 钉钉机器人"
echo ""
echo "  日志:"
echo "    tail -30 data/checkin.log / data/cookie-server.log / data/dingtalk-bot.log"
echo ""
echo "  油猴脚本(浏览器直接安装已配置副本, 无需手动改):"
echo "    $US_DIST"
echo "    SERVER_URL: $SERVER_URL"
echo "    TOKEN:      $COOKIE_TOKEN"
echo ""
echo "  验证下载端点: curl -s http://127.0.0.1:8766/api/health"
echo "  卸载:         ./deploy/uninstall.sh (用普通用户运行)"
