# TJUPT 自动化工具

北洋园 PT 站 (https://tjupt.org) 的自动化脚本集合，基于 NexusPHP。

## 环境要求

- **硬件**: ARM64 (RK3566, 4GB RAM) 或 x86_64
- **系统**: Linux (Debian/Ubuntu)
- **Python**: 3.11+
- **conda**: 用于环境管理

## 安装

```bash
# 1. 创建 conda 环境
conda create -n tjupt python=3.11 -y

# 2. 安装 Tesseract OCR 及其中文语言包
conda install -n pt -c conda-forge tesseract pytesseract pillow requests -y

# 3. 验证安装
~/miniconda3/envs/pt/bin/tesseract --list-langs | grep chi_sim
~/miniconda3/envs/pt/bin/python -c "import pytesseract, PIL, requests; print('OK')"
```

> **注意**: ARM64 设备 (如 RK3566) 推荐通过 conda 安装 Tesseract。x86_64 设备也可以使用 `sudo apt install tesseract-ocr tesseract-ocr-chi-sim`。

## 项目结构

```
tjupt/
├── README.md              # 本文件
├── tjupt_login.py         # 登录模块
├── tjupt_sign.py          # 自动签到 (OCR 识别电影海报)
├── tjupt_search.py        # 种子搜索
├── tjupt_diagnose.py      # 登录诊断工具 (开发用)
└── tjupt_cookies.txt      # Cookie 存储文件
```

## 1. 登录模块 (`tjupt_login.py`)

所有脚本的基础模块，提供 `login()` 函数。

```python
from tjupt_login import login

session = login(verbose=True)   # 返回 requests.Session 或 None
```

直接运行:
```bash
python3 tjupt_login.py
```

## 2. 自动签到 (`tjupt_sign.py`)

自动完成「签到得魔力」——使用本地 Tesseract OCR 识别电影海报，匹配选项后自动提交。

**原理**:
1. 登录 TJUPT
2. 访问签到页面，获取电影海报和 6 个选项
3. 下载海报 → 图像预处理 (放大/灰度/增强) → Tesseract OCR 识别文字
4. 将 OCR 结果与选项做逐字+子串匹配
5. 匹配置信度达到阈值则自动提交，否则换题重试 (最多 10 次)

**运行**:
```bash
~/miniconda3/envs/pt/bin/python tjupt_sign.py
```

**定时签到** (crontab):
```bash
# 每天 8:03 自动签到
3 8 * * * ~/miniconda3/envs/pt/bin/python ~/pt/sites/tjupt/tjupt_sign.py >> ~/pt/sites/tjupt/sign.log 2>&1
```

## 3. 种子搜索 (`tjupt_search.py`)

搜索 TJUPT 种子资源，支持分类过滤、排序、分页、在线下载。

### 基本用法

```bash
# 关键字搜索
python3 tjupt_search.py "星际穿越"

# 按分类过滤
python3 tjupt_search.py "2160p" --cat 401              # 仅电影
python3 tjupt_search.py "1080p" --cat 401 405          # 电影 + 动漫

# 排序
python3 tjupt_search.py "test" --sort seeders           # 按做种数排序
python3 tjupt_search.py "test" --sort size --order asc  # 按文件大小升序

# 分页 (每页 100 条)
python3 tjupt_search.py "test" --page 2                # 第 3 页

# 下载种子
python3 tjupt_search.py "星际穿越" --download 1 --dl-dir /tmp

# 简洁输出格式
python3 tjupt_search.py "1080p" --output simple
```

### 参数说明

| 参数 | 说明 | 可选值 |
|------|------|--------|
| `keyword` | 搜索关键字 | 任意文本 |
| `--cat` | 分类 ID | 见下方分类表 |
| `--area` | 搜索范围 | title, subtitle, uploader, imdb, douban |
| `--mode` | 搜索模式 | and, or, exact |
| `--sort` | 排序字段 | default, title, comments, time, size, seeders, leechers, snatched, uploader |
| `--order` | 排序顺序 | asc, desc |
| `--page` | 页码 (0-based) | 整数 |
| `--incldead` | 断种过滤 | 0=全部, 1=仅活种, 2=仅断种 |
| `--download N` | 下载第 N 个结果 | 整数 |
| `--dl-dir` | 下载目录 | 路径 |
| `--output` | 输出格式 | table, simple |

### 分类 ID

| ID | 分类 | ID | 分类 |
|----|------|----|------|
| 401 | 电影 | 407 | 体育 |
| 402 | 剧集 | 408 | 软件 |
| 403 | 综艺 | 409 | 游戏 |
| 404 | 资料 | 410 | 其他 |
| 405 | 动漫 | 411 | 纪录片 |
| 406 | 音乐 | 412 | 移动视频 |

### 返回字段

| 字段 | 说明 | 示例 |
|------|------|------|
| 作品类型 | 分类名称 | 电影 |
| 标题 | 种子完整标题 | [美国][星际穿越][Interstellar...] |
| 副标题 | 别名/字幕/演员等 | PTP Golden Popcorn \| 豆瓣 Top250 |
| 添加时间 | 上传时间 | 2019-04-11 00:09:46 |
| 种子大小 | 文件大小 | 21.06 GiB |
| 种子数 | 当前做种人数 | 67 |
| 下载数 | 当前下载人数 | 0 |
| 完成数 | 累计完成下载数 | 1771 |
| 评论数 | 评论数量 | 5 |
| 发布者 | 上传者用户名 | 匿名 |
| 详情链接 | 种子详情页 | https://tjupt.org/details.php?id=178732 |
| 下载链接 | 种子文件直链 | https://tjupt.org/download.php?id=178732 |

## 依赖清单

| 包名 | 用途 | 安装方式 |
|------|------|----------|
| tesseract | OCR 引擎 (C++, ~5MB) | conda |
| pytesseract | Tesseract Python 封装 | conda |
| Pillow | 图像处理 | conda |
| requests | HTTP 请求 | conda |

## 注意事项

1. 请勿频繁请求，避免对服务器造成压力
2. 签到页明确标注「禁止使用任何自动化脚本/程序进行签到」，使用本脚本需自行承担风险
3. 回答错误会扣除魔力值，本脚本通过置信度阈值降低错误率
4. Cookie 过期后脚本会自动重新登录
5. 如遇「异地登录保护」提示，需使用与上次登录相同的网络环境
