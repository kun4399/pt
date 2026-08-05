#!/usr/bin/env bash
# ============================================================
# PT 站每日自动签到 systemd 服务一键安装脚本
#
# 用法:
#   ./deploy/install.sh             # 一键安装(含钉钉测试消息)
#   ./deploy/install.sh --no-test   # 跳过钉钉测试消息
#   ./deploy/install.sh --dry-run   # 只预览要执行的命令, 不执行
#
# 说明:
#   - sudo 操作会提示输入密码
#   - 可重复执行(幂等, 重跑会覆盖单元并重新启用)
#   - 单元文件的 User/Group 自动替换为当前用户
#   - 安装后每天 08:10 自动四站签到, 日志 data/checkin.log,
#     签到失败/登录失效/cookie 失效 → 钉钉通知
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE="pt-checkin.service"
TIMER="pt-checkin.timer"
# conda env pt 的 python(可用环境变量 PYTHON 覆盖)
PYTHON="${PYTHON:-/home/kun/miniconda3/envs/pt/bin/python}"
LOG_FILE="$PROJECT_ROOT/data/checkin.log"

TEST_NOTIFY=1
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --no-test) TEST_NOTIFY=0 ;;
        --dry-run) DRY_RUN=1 ;;
        *) echo "未知参数: $arg (支持 --no-test / --dry-run)" >&2; exit 1 ;;
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

cd "$PROJECT_ROOT"

say "PT 四站每日自动签到 systemd 服务安装"
echo "  项目目录: $PROJECT_ROOT"
[ "$DRY_RUN" = "1" ] && echo "  模式: dry-run (仅预览)"

# ---- 1. 前置检查 ----
say "检查前置条件"
[ -f "$PYTHON" ] || fail "未找到 conda python: $PYTHON (可用 PYTHON= 环境变量覆盖)"
[ -f "$SCRIPT_DIR/$SERVICE" ] || fail "缺少单元文件: deploy/$SERVICE"
[ -f "$SCRIPT_DIR/$TIMER" ] || fail "缺少单元文件: deploy/$TIMER"
command -v systemctl >/dev/null 2>&1 || fail "systemctl 不可用"
command -v sudo >/dev/null 2>&1 || fail "sudo 不可用"
ok "前置检查通过"

# ---- 2. 钉钉配置检查 ----
if grep -q "^DINGTALK_WEBHOOK=." "$PROJECT_ROOT/.env" 2>/dev/null \
   && grep -q "^DINGTALK_SECRET=." "$PROJECT_ROOT/.env" 2>/dev/null; then
    ok "钉钉通知已配置 (DINGTALK_WEBHOOK / DINGTALK_SECRET)"
else
    warn ".env 未配置 DINGTALK_WEBHOOK / DINGTALK_SECRET → 签到失败时不会收到钉钉通知"
    warn "稍后可在 $PROJECT_ROOT/.env 追加这两个配置项"
fi

# ---- 3. 钉钉测试消息(默认发送, 验证加签) ----
if [ "$TEST_NOTIFY" = "1" ]; then
    say "发送钉钉测试消息"
    run "$PYTHON" "$PROJECT_ROOT/pt_checkin.py" --notify-test
    ok "测试消息已发送, 请在钉钉确认收到"
else
    say "跳过钉钉测试消息 (--no-test)"
fi

# ---- 4. 预建日志文件(保持当前用户属主, 否则 systemd 首启以 root 创建) ----
say "预建日志文件"
mkdir -p "$PROJECT_ROOT/data"
run touch "$LOG_FILE"
ok "日志文件: $LOG_FILE"

# ---- 5. 安装 systemd 单元(Unit 的 User/Group 替换为当前用户) ----
say "安装签到单元 (需要 sudo 密码)"
run sudo cp "$SCRIPT_DIR/$SERVICE" /etc/systemd/system/ && \
run sudo sed -i "s/^User=.*/User=$(id -un)/; s/^Group=.*/Group=$(id -gn)/" "/etc/systemd/system/$SERVICE"
run sudo cp "$SCRIPT_DIR/$TIMER" /etc/systemd/system/
run sudo systemctl daemon-reload
run sudo systemctl enable --now "$TIMER"
ok "已安装并启用 $TIMER (每天 08:10 自动签到, 开机自启, Persistent 开机补跑)"

# ---- 6. cookie 接收服务 ----
# 6.1 COOKIE_SERVER_TOKEN(未配置才生成, 幂等)
ENV_FILE="$PROJECT_ROOT/.env"
if grep -q "^COOKIE_SERVER_TOKEN=." "$ENV_FILE" 2>/dev/null; then
    COOKIE_TOKEN="$(grep '^COOKIE_SERVER_TOKEN=' "$ENV_FILE" | head -1 | cut -d= -f2)"
else
    say "生成 COOKIE_SERVER_TOKEN (写入 .env)"
    COOKIE_TOKEN="$(openssl rand -hex 16 2>/dev/null || head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)"
    printf '\n# ---- cookie 接收服务(油猴脚本 → 服务器, 公网暴露必须) ----\nCOOKIE_SERVER_TOKEN=%s\n' "$COOKIE_TOKEN" >> "$ENV_FILE"
    ok "已生成 COOKIE_SERVER_TOKEN"
fi

# 6.2 预建 cookie-server.log
say "预建 cookie-server 日志文件"
run touch "$PROJECT_ROOT/data/cookie-server.log"
ok "日志文件: $PROJECT_ROOT/data/cookie-server.log"

# 6.3 安装 pt-cookie-server.service
say "安装 cookie 接收服务单元 (常驻监听 127.0.0.1:8766)"
run sudo cp "$SCRIPT_DIR/pt-cookie-server.service" /etc/systemd/system/ && \
run sudo sed -i "s/^User=.*/User=$(id -un)/; s/^Group=.*/Group=$(id -gn)/" "/etc/systemd/system/pt-cookie-server.service"
run sudo systemctl daemon-reload
run sudo systemctl enable --now pt-cookie-server.service
ok "已安装并启用 pt-cookie-server.service (常驻, Restart=always)"

# 6.4 frpc.toml 追加 pt-cookie 穿透(幂等)
FRPC_TOML="${FRPC_TOML:-/home/kun/frp/frpc.toml}"
if [ -f "$FRPC_TOML" ]; then
    if grep -q 'name = "pt-cookie"' "$FRPC_TOML"; then
        ok "frpc.toml 已含 pt-cookie 穿透"
    else
        say "追加 frp 穿透到 $FRPC_TOML"
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

# ---- 7. 生成油猴脚本已配置副本(填好 SERVER_URL/TOKEN, 直接安装即可) ----
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

# ---- 8. 完成 ----
say "安装完成"
echo "  签到定时器: systemctl list-timers --all | grep pt-checkin"
echo "  手动签到:   sudo systemctl start pt-checkin.service"
echo "  签到日志:   tail -30 $PROJECT_ROOT/data/checkin.log"
echo "  cookie 服务: sudo systemctl status pt-cookie-server.service"
echo "  cookie 日志: tail -30 $PROJECT_ROOT/data/cookie-server.log"
echo "  通知测试:   $PYTHON $PROJECT_ROOT/pt_checkin.py --notify-test"
echo ""
say "油猴脚本(推荐直接安装已配置副本, 无需手动改):"
echo "  $US_DIST"
echo "  (模板: userscripts/pt-cookie-sender.user.js, 需手动填 TOKEN)"
echo "  SERVER_URL: $SERVER_URL"
echo "  TOKEN:      $COOKIE_TOKEN"
echo "  卸载:       sudo systemctl disable --now pt-checkin.timer && sudo rm /etc/systemd/system/pt-checkin.*"
