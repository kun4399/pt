# PTerClub CLI

[pterclub.net](https://pterclub.net) 命令行搜索工具，支持按关键词检索种子。

## 依赖

| 软件 | 版本 | 用途 |
|------|------|------|
| Python | ≥ 3.9 | 运行环境 |
| requests | ≥ 2 | HTTP 请求 |
| beautifulsoup4 | ≥ 4 | HTML 解析 |
| lxml | ≥ 5 | XML/HTML 解析器 |

### 安装

```bash
# 创建 conda 环境（或直接用系统 Python）
conda create -n pt python=3.11 -y （或用项目根 environment.yml 一键创建）
conda activate pt
pip install requests beautifulsoup4 lxml
```

## 初始化

首次使用需要从浏览器导出 Cookie。

### 方法 1：油猴脚本（推荐）

1. 浏览器安装 [Tampermonkey](https://www.tampermonkey.net/) 扩展
2. 导入本项目中的 `pterclub-cookie-exporter.user.js`
3. 打开 https://pterclub.net 并登录
4. 点击页面右下角 `🍪 Export` 按钮
5. Cookie 已复制到剪贴板，保存到项目目录下的 `cookies.json`

### 方法 2：手动导出

1. 浏览器打开 https://pterclub.net 并登录
2. F12 → Application → Cookies → https://pterclub.net
3. 将所有 cookie 按以下格式保存：

```json
{
  "saved_at": "2026-07-27T00:00:00",
  "cookies": [
    {"name": "PHPSESSID", "value": "...", "domain": "pterclub.net", "path": "/", "secure": true},
    {"name": "c_secure_uid", "value": "...", "domain": "pterclub.net", "path": "/", "secure": true},
    ...
  ]
}
```

## 用法

```bash
conda activate pt

# 检查 cookie 是否有效
python3 pterclub.py check

# 搜索种子
python3 pterclub.py search "4K HDR"
python3 pterclub.py search "BluRay" -n 20
python3 pterclub.py search "movie" --json
```

### 输出示例

```
  [4K HDR] — 5 result(s)

  Type              Title                                  Alive      Size          S     L     C
  ─────────────────────────────────────────────────────────────────────────────────────────────────
  电影 / Encode      Spotlight 2015 UHD BluRay 2160p...     2分         24.37GB       1     2     0
                     | 聚焦/焦点追击(港)/惊爆焦点(台) mUHD作品 4k 杜比视界...
                     | Tags: 国语, 英字, 中字
                     | 📥 https://pterclub.net/download.php?id=868014&passkey=...

  电影 / Encode      Fight Club 1999 UHD BluRay 2160p...    5分         32.03GB       1     4     0
                     | 搏击俱乐部 mUHD作品 4k 杜比视界HDR10+...
                     | Tags: 国语, 英字, 中字
                     | 📥 https://pterclub.net/download.php?id=868013&passkey=...
```

### 输出字段

| 字段 | 说明 |
|------|------|
| Type | 种子类型（电影/剧集/音乐...）及标签（Encode/字幕等） |
| Title | 主标题（含年份、分辨率、编码格式） |
| Subtitle | 副标题（中文名、导演、简介） |
| Alive | 存活时间 |
| Size | 文件大小 |
| S | 做种数 |
| L | 下载数 |
| C | 完成数 |
| Tags | 语言/字幕标签 |
| 📥 | 种子下载链接（含 passkey） |

## 文件结构

```
ptclub/
├── pterclub.py                          # 主脚本
├── pterclub-cookie-exporter.user.js     # 油猴脚本（浏览器导入）
├── cookies.json                         # Cookie 持久化文件
└── README.md
```

## 常见问题

**Q: 搜索提示 "Cookie 已失效"？**

浏览器重新登录 pterclub.net，点击油猴按钮重新导出 Cookie，覆盖项目目录下的 `cookies.json`。

**Q: 为什么不用脚本直接登录？**

站点使用了 Cloudflare Turnstile 人机验证，无法自动化。通过浏览器登录一次导出 cookie 后，可长期复用。

**Q: ARM 设备能用吗？**

可以。纯 Python 依赖，均支持 aarch64，无需浏览器，内存占用极小。
