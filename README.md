# PT 站自动化工具集

四个 PT 站(均为 NexusPHP 内核)的登录 / 签到 / 搜索 / 下载脚本统一项目。

| 站点 | URL | 脚本 | 功能 |
|---|---|---|---|
| azusa.wiki | https://azusa.wiki | `sites/azusapt/azusa_login.py` | 登录(ddddocr 验证码)+ 种子搜索 + 封禁诊断 |
| u2.dmhy.org | https://u2.dmhy.org | `sites/dmhypt/login.py`, `dmhy.py` | 登录(3 模式降级)+ 签到(作品名验证码)+ 搜索 |
| pterclub.net | https://pterclub.net | `sites/ptclub/pterclub.py` | 种子搜索 + cookie 有效性检查(浏览器导出 cookie) |
| tjupt.org | https://tjupt.org | `sites/tjupt/tjupt_login.py`, `tjupt_sign.py`, `tjupt_search.py` | 登录 + 海报 OCR 签到 + 搜索/下载 |

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
| `TJPT_*` | tjupt.org | 用户名/密码 |
| `DMHY_*` | u2.dmhy.org | 用户名/密码/登录 cookie(登录成功自动写回 `DMHY_COOKIE`) |
| `HTTP_PROXY` / `HTTPS_PROXY` | 全局 | 仅被 dmhy 显式读取;其他站直连(不受影响) |

cookie 文件随各自站点目录存放(格式各不相同,互不复用):
`azusa_cookies.txt`(Netscape)、`tjupt_cookies.txt`(name=value)、`cookies.pkl`(pickle)、`cookies.json`(浏览器导出)。

## 快速用法

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

或使用 Makefile 入口: `make azusa-search KW="汉化"` 等(见 Makefile)。

每个站点的详细用法、参数表、cookie 刷新方式见 `sites/<站>/README.md`。

## 定时签到示例 (crontab)

```bash
# 每天 8:03 tjupt 海报签到
3 8 * * * /home/kun/miniconda3/envs/pt/bin/python /home/kun/pt/sites/tjupt/tjupt_sign.py >> /home/kun/pt/sites/tjupt/sign.log 2>&1
```

## 风控警告(务必阅读)

- **azusa.wiki**: 直连 IP 曾被触发登录超限封禁(8 天+)。真实登录/搜索必须走 `AZUSA_PROXY`,且代理出口 IP 同样受"剩余尝试次数"保护,频繁触发会连累代理 IP。
- **tjupt.org**: 有"异地登录保护",更换网络/IP 后登录会被拒绝(脚本会打印当前 IP)。签到属站点禁止的自动化行为,风险自负。
- **u2.dmhy.org**: 登录页有剩余尝试次数计数,脚本在 ≤3 次时拒绝登录以防封 IP;优先使用 cookie 模式。
- **pterclub.net**: 站点有 Cloudflare Turnstile,脚本不做自动化登录——用浏览器登录后通过油猴脚本 `sites/ptclub/pterclub-cookie-exporter.user.js` 导出 cookie 存为 `sites/ptclub/cookies.json`。

## 目录结构

```
pt/
├── common/                 # 共享模块 (constants/env/http/cookies/format/search)
├── sites/                  # 四个站点目录(各站独立可运行)
│   ├── azusapt/  dmhypt/  ptclub/  tjupt/
├── data/                   # 历史搜索导出样例
├── .env / .env.example     # 统一凭据配置
├── environment.yml         # conda 环境定义 (name: pt)
├── requirements.txt        # pip 依赖清单
└── Makefile                # 便捷入口
```
