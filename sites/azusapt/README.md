# azusapt — azusa.wiki 自动登录 & 种子搜索工具

自动登录 [azusa.wiki](https://azusa.wiki)（梓喵，NexusPHP 二次元 PT 站），并按关键词搜索种子、提取完整信息。

## 功能

- **自动登录**：获取验证码图片 → `ddddocr` 深度学习识别 → 提交登录
- **Cookie 持久化**：每次运行登录一次并保存到 `azusa_cookies.txt`；登录被拒/失败时优先复用本地 cookie（有效则继续操作，搜索不消耗登录次数）
- **种子搜索**：按关键词搜索，解析并输出作品类型、标题、副标题、大小、种子数/下载数/完成数、存活时间、下载链接等
- **风控保护**：
  - 最大登录尝试次数仅 5 次（站点阈值 8 次）
  - 登录前读取剩余尝试次数，**≤2 次时输出警告并拒绝登录**
  - 检测到 IP 封锁 / Login 锁定立即停止，不浪费次数
  - 登录成功后所有操作走 cookie，不再触发登录

## 环境

复用 conda 环境 **`pt`**（已有 `ddddocr`、`pillow`、`requests`；补装了 `beautifulsoup4`、`lxml`）：

```bash
conda run -n pt python3 azusa_login.py --search "关键词"
```

## 用法

```bash
# 搜索种子（自动复用 cookie，过期则登录）
conda run -n pt python3 azusa_login.py --search "汉化"

# 搜索第 2 页
conda run -n pt python3 azusa_login.py --search "东立" --page 1

# 简洁表格模式
conda run -n pt python3 azusa_login.py --search "完结" --concise

# 只输出 JSON
conda run -n pt python3 azusa_login.py --search "汉化" --json-only

# 走 HTTP 代理（本机 IP 被封禁时使用，如 127.0.0.1:7890）
conda run -n pt python3 azusa_login.py --search "汉化" --proxy http://127.0.0.1:7890
```

## 搜索结果字段

| 字段 | 说明 |
|------|------|
| `id` | 种子 ID |
| `title` / `subtitle` | 标题 / 副标题（汉化组等） |
| `category` | 作品类型（Game、漫画等，来自类型图标 title） |
| `tags` | 标签（全存档、电子版、自购、禁转、官方中字…） |
| `size_raw` / `size_value` / `size_unit` | 种子大小 |
| `seeders` / `leechers` / `completed` | 做种数 / 下载中 / 已完成数 |
| `upload_time_label` / `upload_time_iso` | 存活时间（如 "1年7月"）+ 精确时间戳 |
| `remaining_time` / `remaining_time_deadline` | 免费促销剩余时间 + 截止时间 |
| `promotion` | 促销类型（免费 / 2X / 50% / 30%） |
| `is_hot` / `sticky_level` | 热门 / 置顶标记 |
| `comments` | 评论数 |
| `detail_url` / `download_url` | 详情页链接 / .torrent 下载链接 |

## 文件

```
azusa_login.py     # 主脚本（登录 + 搜索）
azusa_cookies.txt  # 登录后自动保存的 cookie（Netscape 格式）
```

## 工作原理

1. GET `index.php?title=Special:UserLogin` → 提取 `csrf_token`、`imagehash`
2. GET `image.php?action=regimage&imagehash=...` → 获取验证码图片
3. `ddddocr` 识别图片文字
4. POST `takelogin.php`（字段：`csrf_token`、`username`、`password`、`imagestring`、`imagehash`、`logout`、`securelogin`、`ssl`、`trackerssl`）
5. 登录成功 → 保存 cookie；失败 → 按剩余次数决定重试或放弃
6. 搜索：GET `torrents.php?search=关键词` → BeautifulSoup 解析表格行

## 现状

> **⚠️ 2026-07-27 本机直连 IP 被站点风控封禁，截至 2026-08-05 仍未自动解除。**

原因：调试搜索功能时反复运行多个测试脚本，每次触发登录，累计尝试超过站点 8 次限制，触发了 "Login 锁定！认证的最大错误尝试次数已到" + "我们怀疑你在欺骗系统，因此禁用了你的IP地址！"。

- 封禁按 IP 生效：直连出口 IP 的所有请求都会被服务器拒绝，**cookie 复用也无法绕过**（服务器在 cookie 验证前就拒绝）
- 本次封禁已持续 8 天以上仍未解除，不建议干等；**走代理可正常访问**（代理出口 IP 不在封禁名单）
- 当前可用方式（本机代理已开启，HTTP 端口 7890）：

  ```bash
  conda run -n pt python3 azusa_login.py --search "汉化" --proxy http://127.0.0.1:7890
  ```

- 风控提醒：脚本登录前会检测剩余尝试次数，**≤2 次时拒绝登录并回退本地 cookie**；不要手动反复触发登录
