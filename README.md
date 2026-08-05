# PT 站自动化工具集

四个 PT 站(均为 NexusPHP 内核)的登录 / 签到 / 搜索 / 下载脚本统一项目。

| 站点 | URL | 脚本 | 功能 |
|---|---|---|---|
| azusa.wiki | https://azusa.wiki | `sites/azusapt/azusa_login.py` | 登录(ddddocr 验证码)+ 种子搜索 + 封禁诊断(签到系统已官方下线) |
| u2.dmhy.org | https://u2.dmhy.org | `sites/dmhypt/login.py`, `dmhy.py` | 登录(3 模式降级)+ 签到(作品名验证码)+ 搜索 |
| pterclub.net | https://pterclub.net | `sites/ptclub/pterclub.py` | 种子搜索 + 签到(attendance-ajax.php)+ cookie 有效性检查 |
| tjupt.org | https://tjupt.org | `sites/tjupt/tjupt_login.py`, `tjupt_sign.py`, `tjupt_search.py` | 登录 + 海报 OCR 签到 + 搜索/下载 |

**统一入口**: `pt_search.py`(一次搜索全部四站,统一表格输出,含站点来源)与 `pt_checkin.py`(一次签到全部四站,azusa 自动跳过,见下文"快速用法")。

公共逻辑(会话构造、cookie 存取、登录态检查、解析原语、格式化)在 `common/` 包;各站点脚本保持独立可运行。

## 环境安装

统一使用 conda 环境 **`pt`**(Python 3.11),覆盖四个站点全部依赖:

```bash
cd /home/kun/pt
conda env create -f environment.yml      # 或 pip install -r requirements.txt
```

验证:

```bash
conda run -n pt python -c "import requests, bs4, lxml, dotenv, ddddocr, pytesseract, PIL, rich; print('OK')"
conda run -n pt tesseract --list-langs | grep chi_sim   # 中文 OCR 语言包
```

注意事项:
- **tesseract 是二进制引擎**(签到 OCR 用),conda-forge 版本自带 chi_sim/chi_tra/eng。x86_64 也可 `sudo apt install tesseract-ocr tesseract-ocr-chi-sim`。
- **ARM64 (RK3566)**: ddddocr 1.5.6 + onnxruntime 1.22.1 已在本机验证可用;若 pip 解析异常,固定版本 `pip install onnxruntime==1.22.1 ddddocr==1.5.6`。
- **ddddocr 首次运行需联网下载模型**;离线环境需预置模型文件。
- 原分散环境(dmhy / ptclub / tjupt)已删除,统一使用 `pt`;`zjusport` 环境保留(其他项目在用)。

## 配置

所有凭据集中在根目录 `.env`(已被 .gitignore 排除):

```bash
cp .env.example .env   # 首次使用
```

| 前缀 | 站点 | 说明 |
|---|---|---|
| `AZUSA_*` | azusa.wiki | 用户名/密码/代理(`AZUSA_PROXY` 默认代理,直连 IP 曾封禁) |
| `TJPT_*` | tjupt.org | 用户名/密码(显式直连,不走代理——该站拒绝非中国 IP) |
| `DMHY_*` | u2.dmhy.org | 用户名/密码/登录 cookie(登录成功自动写回 `DMHY_COOKIE`) |
| `HTTP_PROXY` / `HTTPS_PROXY` | 全局 | 被 dmhy、ptclub 显式读取(`http://127.0.0.1:7890`,clash);tjupt 不受影响(直连) |

代理策略(2026-08):tjupt 走直连(TUN 模式下 clash 规则 `GEOIP,CN,DIRECT` 兜底),
其余站点默认走 7890 代理;azusa 单独读 `AZUSA_PROXY`,dmhy/ptclub 读全局代理。

cookie 文件随各自站点目录存放(格式各不相同,互不复用):
`azusa_cookies.txt`(Netscape)、`tjupt_cookies.txt`(name=value)、`cookies.pkl`(pickle)、`cookies.json`(浏览器导出)。

## 快速用法

**统一入口(推荐)**:搜索默认全部四站,统一表格输出(含站点来源列);签到默认四站全签:

```bash
# 全站搜索(输出统一格式, 含站点列)
conda run -n pt python pt_search.py "汉化"
# 指定站点站内搜索(逗号分隔)
conda run -n pt python pt_search.py "4K" --site azusa,tjupt
# 登录前预检: 网络可达性 + 剩余登录次数(≤2 警告不登录) + 本地 cookie 登录态
conda run -n pt python pt_search.py --check
# JSON 输出(权威格式, 含全部 URL) / 限制条数 / 打印详情链接
conda run -n pt python pt_search.py "4K" --json
conda run -n pt python pt_search.py "4K" --limit 30 -v

# 四站自动签到(azusa 签到下线自动跳过; 退出码 0 = 全部正常)
conda run -n pt python pt_checkin.py
# 指定站点签到 / JSON 输出 / 只预检不签到
conda run -n pt python pt_checkin.py --site tjupt,dmhy
conda run -n pt python pt_checkin.py --json
conda run -n pt python pt_checkin.py --check
```

各站独立脚本(保持原样,格式各异,供单站/定时任务使用):

```bash
# azusa.wiki —— 搜索(默认走 AZUSA_PROXY)
conda run -n pt python sites/azusapt/azusa_login.py --search "汉化"

# tjupt.org —— 海报 OCR 签到
conda run -n pt python sites/tjupt/tjupt_sign.py
# tjupt 搜索
conda run -n pt python sites/tjupt/tjupt_search.py "星际穿越" --cat 401

# u2.dmhy.org —— 登录(自动选 cookie/OCR/手动模式)、签到、搜索
conda run -n pt python sites/dmhypt/login.py
conda run -n pt python sites/dmhypt/dmhy.py checkin
conda run -n pt python sites/dmhypt/dmhy.py search "4K"

# pterclub.net —— 检查 cookie、搜索
conda run -n pt python sites/ptclub/pterclub.py check
conda run -n pt python sites/ptclub/pterclub.py search "4K" -n 5
```

或使用 Makefile 入口: `make azusa-search KW="汉化"`、`make pt-search KW="4K"`、
`make pt-search-site KW="汉化" SITE=azusa,tjupt`、`make pt-check` 等(见 Makefile)。

每个站点的详细用法、参数表、cookie 刷新方式见 `sites/<站>/README.md`。

## systemd 定时签到 + 钉钉通知(推荐)

每天 08:10 自动四站签到,日志写 `data/checkin.log`;登录失效(自动登录重试 3 次仍失败)、
cookie 失效(ptclub/dmhy 需手动更新)、签到失败时通过钉钉机器人通知。

前置:`.env` 已配置 `DINGTALK_WEBHOOK` / `DINGTALK_SECRET`(自定义机器人"加签"安全设置)。

### 一键安装

```bash
cd /home/kun/pt && ./deploy/install.sh        # 一键安装(自动发一条钉钉测试消息)
./deploy/install.sh --no-test                 # 跳过测试消息
./deploy/install.sh --dry-run                 # 只预览要执行的命令
```

脚本自动完成:前置检查 → 钉钉配置检查 → 测试消息 → 预建日志 `data/checkin.log` →
安装 `pt-checkin.service`/`.timer`(User/Group 自动替换为当前用户)→ 启用 timer。幂等,可重复执行。

### 手动安装(等价步骤)

```bash
cd /home/kun/pt
/home/kun/miniconda3/envs/pt/bin/python pt_checkin.py --notify-test   # 钉钉链路测试
mkdir -p data && touch data/checkin.log                                # 预建日志(kun 属主)
sudo cp deploy/pt-checkin.service /etc/systemd/system/
sudo cp deploy/pt-checkin.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pt-checkin.timer
sudo systemctl start pt-checkin.service        # 手动触发一次真实签到
systemctl list-timers --all | grep pt-checkin  # 确认 timer 生效
```

- **通知条件**: 签到失败 / 登录失效且自动登录重试 3 次仍失败 / cookie 失效(ptclub/dmhy 无法自动登录, 提示手动更新)→ 钉钉消息;全部成功不通知
- **手动测试通知**: `python pt_checkin.py --notify-test`(发一条测试消息);`python pt_checkin.py --notify` 手动跑一次带通知的签到
- **日志**: `data/checkin.log`(systemd append 写入);日志增长可用 `truncate -s 0 data/checkin.log` 清空
- **状态**: 失败日 `sudo systemctl status pt-checkin.service` 显示 failed 为预期(此时已发钉钉通知),timer 下次照常触发
- **开机补跑**: timer 的 `Persistent=true`,重启错过签到时间会自动补跑;服务启动前最多等 3 分钟 clash(7890)就绪
- **卸载**: `sudo systemctl disable --now pt-checkin.timer && sudo rm /etc/systemd/system/pt-checkin.*`

## 定时签到示例 (crontab, 替代方案)

```bash
# 每天 08:10 四站统一自动签到(azusa 自动跳过; 退出码 0 = 全部正常)
10 8 * * * cd /home/kun/pt && /home/kun/miniconda3/envs/pt/bin/python pt_checkin.py >> data/checkin.log 2>&1

# 或仅 tjupt 海报签到(站点禁止自动化, 风险自负)
3 8 * * * /home/kun/miniconda3/envs/pt/bin/python /home/kun/pt/sites/tjupt/tjupt_sign.py >> /home/kun/pt/sites/tjupt/sign.log 2>&1
```

## 风控警告(务必阅读)

- **azusa.wiki**: 直连 IP 曾被触发登录超限封禁(8 天+)。真实登录/搜索必须走 `AZUSA_PROXY`,且代理出口 IP 同样受"剩余尝试次数"保护,频繁触发会连累代理 IP。统一入口默认 cookie-first(本地 cookie 有效时不登录,避免每次登录消耗次数);`--force-login` 有风控风险,**勿用于定时任务**。**签到系统已官方下线**(attendance.php 无表单,页面"签到成功"为反爬诱饵),统一签到自动跳过。
- **tjupt.org**: 有"异地登录保护",更换网络/IP 后登录会被拒绝(脚本会打印当前 IP)。该保护无法通过 GET 登录页预检(仅在提交登录后出现),统一入口登录失败会明确提示"需在常用网络/IP 下登录"。**站点规则明确禁止自动化签到**,风险自负;OCR 识别失败会换题重试(最多 10 次)。
- **u2.dmhy.org**: 登录页有剩余尝试次数计数,脚本在 ≤2 次时拒绝登录以防封 IP;优先使用 cookie 模式(统一入口不做自动登录, cookie 失效时提示先运行 `sites/dmhypt/login.py`)。签到为作品名验证码,属站点禁止的自动化行为,风险自负。
- **pterclub.net**: 站点有 Cloudflare Turnstile,脚本不做自动化登录——用浏览器登录后通过油猴脚本 `sites/ptclub/pterclub-cookie-exporter.user.js` 导出 cookie 存为 `sites/ptclub/cookies.json`。签到为 GET `attendance-ajax.php`(无参数,仅 cookie+Referer)。

统一入口的登录前预检(`pt_search.py --check` / `pt_checkin.py --check`):先检测网络能否访问登录页 → 再检测剩余登录次数(≤2 输出警告不登录)→ 最后检测本地 cookie 登录态。tjupt 无次数机制显示 N/A;ptclub 预检即 cookie 有效性检查。统一签到(`pt_checkin.py`)对每站先预检再签到,单站失败不影响其他站。

## 目录结构

```
pt/
├── pt_search.py            # 统一入口: 全站搜索 / --site 站内搜索 / --check 预检 / --json
├── pt_checkin.py           # 统一签到: 四站自动签到(azusa 自动跳过) / --site / --json
├── common/                 # 共享模块 (constants/env/http/cookies/format/search)
│   ├── sites.py            #   站点注册表 + 登录前预检 + 搜索结果归一化
│   ├── unified.py          #   四站搜索适配器 + 统一表格/JSON 渲染
│   ├── checkin.py          #   四站签到适配器 + 签到表格/JSON 渲染 + 预检渲染
│   └── notify.py           #   钉钉机器人通知(加签 + 发送)
├── deploy/                 # systemd 单元 (pt-checkin.service + .timer, 安装见 README)
├── sites/                  # 四个站点目录(各站独立可运行)
│   ├── azusapt/  dmhypt/  ptclub/  tjupt/
├── data/                   # 历史搜索导出样例 / 签到日志 (checkin.log)
├── .env / .env.example     # 统一凭据配置
├── environment.yml         # conda 环境定义 (name: pt)
├── requirements.txt        # pip 依赖清单
└── Makefile                # 便捷入口
```
