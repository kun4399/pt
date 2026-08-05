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
cd ~/pt
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

**所有用户可修改项集中在一个地方:根目录 `.env`**(已被 .gitignore 排除,模板见 `.env.example`):

```bash
cp .env.example .env   # 首次使用
```

### 凭据与网络

| 键 | 说明 |
|---|---|
| `AZUSA_USERNAME/PASSWORD/PROXY` | azusa 账号密码与代理(直连 IP 曾封禁,建议走代理) |
| `TJPT_USERNAME/PASSWORD` | tjupt 账号密码(显式直连,拒绝非中国 IP) |
| `DMHY_USERNAME/PASSWORD/COOKIE` | dmhy 账号密码与登录 cookie(登录成功自动写回) |
| `HTTP_PROXY` / `HTTPS_PROXY` | 全局代理(7890, clash);dmhy/ptclub 显式读取;tjupt 直连不受影响 |
| `DINGTALK_WEBHOOK/SECRET` | 钉钉机器人(签到失败通知,加签安全设置) |
| `COOKIE_SERVER_TOKEN` | cookie 接收服务鉴权(公网暴露必须,install.sh 自动生成) |
| `FRP_PUBLIC_IP` | frp 公网服务器地址(油猴发送/验证码访问) |

### 统一可调参数(留空/删除 = 用代码默认值)

| 键 | 默认 | 说明 |
|---|---|---|
| `HTTP_TIMEOUT` | 30 | HTTP 请求超时秒数(搜索/签到/预检) |
| `RETRY_MAX` | 3 | 签到失败自动重试次数(登录失效→自动登录重试) |
| `RETRY_INTERVAL` | 30 | 重试间隔秒 |
| `ATTEMPTS_WARN` | 2 | 剩余登录次数 ≤N 时警告且不登录 |
| `PREPCHECK_TIMEOUT` | 15 | 登录前预检超时秒数 |
| `AZUSA_MAX_ATTEMPTS` | 5 | azusa 单次运行最大登录尝试 |
| `TJPT_MAX_RETRIES` | 10 | tjupt 海报 OCR 签到最大换题重试 |
| `DMHY_MIN_ATTEMPTS` | 3 | dmhy 剩余次数 <N 时拒绝登录 |
| `DMHY_CAPTCHA_PORT` | 8765 | dmhy 验证码服务端口(login.py 手动模式) |
| `COOKIE_SERVER_HOST/PORT/MAX_BODY` | 127.0.0.1 / 8766 / 1MiB | cookie 接收服务监听地址/端口/body 上限 |
| `COOKIE_DIR` | `data/cookies` | **四站 cookie 文件统一存放目录**(相对项目根,按站点分目录) |

代理策略(2026-08):tjupt 走直连(TUN 模式下 clash 规则 `GEOIP,CN,DIRECT` 兜底),
其余站点默认走 7890 代理;azusa 单独读 `AZUSA_PROXY`,dmhy/ptclub 读全局代理。

**cookie 文件统一存放在 `data/cookies/<站点目录>/`**(`COOKIE_DIR` 可改),各站格式不同:
`azusa_cookies.txt`(Netscape)、`tjupt_cookies.txt`(name=value)、`cookies.pkl`(pickle)、`cookies.json`(浏览器导出)。

**四站统一支持手动 cookie 登录**(跳过账号密码):把对应站的 cookie 文件放进
`data/cookies/<站点目录>/`,或登录网站后用油猴脚本(`userscripts/`)一键发送保存,
统一入口搜索/签到会自动优先使用(见上文"油猴脚本发送 cookie")。
`DMHY_COOKIE`(.env)仅为 dmhy 交互登录脚本 `login.py` 的可选快捷配置(单 cookie),
与统一入口无关——四站的手动 cookie 机制完全一致。

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
cd ~/pt && ./deploy/install.sh        # 一键安装(自动发一条钉钉测试消息; 路径按实际替换)
./deploy/install.sh --no-test         # 跳过测试消息
./deploy/install.sh --dry-run         # 只预览要执行的命令
```

卸载:

```bash
./deploy/uninstall.sh                 # 卸载 systemd 服务(保留配置与数据)
./deploy/uninstall.sh --purge         # 额外删除日志/cookie/油猴副本/frp 穿透
./deploy/uninstall.sh --dry-run       # 只预览
```

脚本自动完成:前置检查 → 钉钉配置检查 → 测试消息 → 预建日志 `data/checkin.log` →
安装 `pt-checkin.service`/`.timer`(User/Group 自动替换为当前用户)→ 启用 timer。幂等,可重复执行。

### 手动安装(等价步骤, 路径按实际替换)

```bash
cd ~/pt
~/miniconda3/envs/pt/bin/python pt_checkin.py --notify-test   # 钉钉链路测试
mkdir -p data && touch data/checkin.log                       # 预建日志
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

## 油猴脚本发送 cookie + HTTP 接收服务

浏览器油猴脚本把当前 PT 站 cookie 一键发送到服务器保存(供自动签到使用),服务经 frp 穿透公网可达。

**架构**: 浏览器(油猴) → `http://<公网IP>:8766/api/cookie`(X-Auth-Token) → frpc 隧道 → `pt-cookie-server`(systemd 常驻, 127.0.0.1:8766) → 按站点格式落盘
(azusa Netscape / tjupt name=value / dmhy pickle + 同步 DMHY_COOKIE / ptclub JSON)。

> 本文档中 `<公网IP>` 均指 frp 服务器的公网地址(本机 install.sh 输出会打印实际值)。

**安装**(`deploy/install.sh` 一键完成, 幂等):

```bash
cd ~/pt && ./deploy/install.sh
```

脚本自动:生成 `COOKIE_SERVER_TOKEN`(写入 .env, 公网暴露鉴权必须) → 安装并启用
`pt-cookie-server.service`(常驻) → `frpc.toml` 追加 pt-cookie 穿透(8766)并重启 frpc → 打印油猴配置。

**油猴脚本安装**:

1. 浏览器装 Tampermonkey → 新建脚本, 内容粘贴 `userscripts/pt-cookie-sender.user.js`
2. 修改脚本头部两行常量:
   - `SERVER_URL`(默认已填 `http://<公网IP>:8766/api/cookie`)
   - `TOKEN` ← 安装脚本结尾输出的 `COOKIE_SERVER_TOKEN` 值(或 `grep COOKIE_SERVER_TOKEN .env`)
3. 登录四个 PT 站任意一个 → 右下角「🍪 发送 Cookie」按钮 → 成功通知「已保存 N 条 cookie」

**免改版**: 运行 `deploy/install.sh` 会自动生成已填好 SERVER_URL/TOKEN 的
`userscripts/pt-cookie-sender.configured.user.js`(含 token, 已被 .gitignore 排除),
浏览器直接安装该文件即可, 无需手动改任何配置。

**服务状态与自测**:

```bash
systemctl status pt-cookie-server.service        # 常驻服务状态
tail -30 data/cookie-server.log                  # 接收日志
curl -s http://127.0.0.1:8766/api/health         # 本地探活
curl -s http://<公网IP>:8766/api/health    # 公网探活(frp 生效后)
```

**安全提示**: 服务经公网暴露, `COOKIE_SERVER_TOKEN` 未配置时服务拒绝启动;
token 内嵌在油猴脚本中, 任何拿到脚本的人可覆盖这 4 个 cookie 文件(可随时轮换
`.env` 中的 token 并同步脚本);服务默认只绑 127.0.0.1 由 frp 转发;body 上限 1 MiB;
`GET /api/health` 无鉴权仅暴露 `{"ok":true}`;日志不记录 cookie 值与 token。

**说明**: HttpOnly 的 cookie 无法被 `document.cookie` 读取, 发送时若缺少关键
cookie(如 tjupt 的 access_token)会收到警告——此时请用浏览器开发者工具或
GM_cookie 处理, 或回退 `sites/ptclub/pterclub-cookie-exporter.user.js` 剪贴板导出。

## 定时签到示例 (crontab, 替代方案)

```bash
# 每天 08:10 四站统一自动签到(azusa 自动跳过; 退出码 0 = 全部正常; 路径按实际替换)
10 8 * * * cd ~/pt && ~/miniconda3/envs/pt/bin/python pt_checkin.py >> data/checkin.log 2>&1

# 或仅 tjupt 海报签到(站点禁止自动化, 风险自负)
3 8 * * * ~/miniconda3/envs/pt/bin/python ~/pt/sites/tjupt/tjupt_sign.py >> ~/pt/sites/tjupt/sign.log 2>&1
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
├── pt_cookie_server.py     # cookie 接收服务启动器(油猴脚本发送的 cookie → 本地保存)
├── common/                 # 共享模块 (constants/env/http/cookies/format/search)
│   ├── sites.py            #   站点注册表 + 登录前预检 + 搜索结果归一化
│   ├── unified.py          #   四站搜索适配器 + 统一表格/JSON 渲染
│   ├── checkin.py          #   四站签到适配器 + 签到表格/JSON 渲染 + 预检渲染
│   ├── notify.py           #   钉钉机器人通知(加签 + 发送)
│   └── cookie_server.py    #   HTTP 接收服务(鉴权 + 按站点格式落盘)
├── userscripts/            # 油猴脚本 (pt-cookie-sender.user.js 四站 cookie 发送)
├── deploy/                 # systemd 单元 (pt-checkin.service+.timer / pt-cookie-server.service, install.sh 一键安装)
├── sites/                  # 四个站点目录(各站独立可运行)
│   ├── azusapt/  dmhypt/  ptclub/  tjupt/
├── data/                   # 历史搜索导出样例 / 签到日志 (checkin.log)
├── .env / .env.example     # 统一凭据配置
├── environment.yml         # conda 环境定义 (name: pt)
├── requirements.txt        # pip 依赖清单
└── Makefile                # 便捷入口
```
