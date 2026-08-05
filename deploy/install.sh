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
say "安装 systemd 单元 (需要 sudo 密码)"
run sudo cp "$SCRIPT_DIR/$SERVICE" /etc/systemd/system/ && \
run sudo sed -i "s/^User=.*/User=$(id -un)/; s/^Group=.*/Group=$(id -gn)/" "/etc/systemd/system/$SERVICE"
run sudo cp "$SCRIPT_DIR/$TIMER" /etc/systemd/system/
run sudo systemctl daemon-reload
run sudo systemctl enable --now "$TIMER"
ok "已安装并启用 $TIMER (每天 08:10 自动签到, 开机自启, Persistent 开机补跑)"

# ---- 6. 完成 ----
say "安装完成"
echo "  查看定时器: systemctl list-timers --all | grep pt-checkin"
echo "  手动签到:   sudo systemctl start pt-checkin.service"
echo "  查看日志:   tail -30 $PROJECT_ROOT/data/checkin.log"
echo "  通知测试:   $PYTHON $PROJECT_ROOT/pt_checkin.py --notify-test"
echo "  卸载:       sudo systemctl disable --now pt-checkin.timer && sudo rm /etc/systemd/system/pt-checkin.*"
