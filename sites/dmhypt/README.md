# u2.dmhy.org 自动登录 + 签到 + 搜索

## 环境

```bash
conda env create -f ../../environment.yml
conda activate pt
cp ../../.env.example ../../.env
# 编辑 .env 填入账号密码
```

OCR 模式需要额外安装（可选）：

```bash
pip install ddddocr pytesseract pillow
```

## 登录

```bash
python login.py
```

OCR 自动登录(cookie-first):

1. 已保存的 `cookies.pkl` 有效则直接通过(无需重新登录)
2. 失效则 OCR 模式: 自动下载验证码直到 ddddocr+tesseract 识别一致后提交一次,**全程无需人工**
3. 登录成功 → 保存 `cookies.pkl`,`dmhy.py`/统一入口直接复用

安全保护: 登录页面显示 `剩余 ≤ N 次尝试`(`.env ATTEMPTS_WARN`, 默认 2)时**拒绝登录**, 防止 IP 被封。

```bash
python login.py                      # cookie 有效则跳过, 否则 OCR 登录
python login.py -v                   # 详细日志
```

## 签到

```bash
python dmhy.py checkin               # 默认留言 "一切随缘~"
python dmhy.py checkin -m "新的一天"  # 自定义留言（≥5字符）
python dmhy.py -v checkin            # 详细日志
```

随机选择一个作品名称提交。答对得 9~59 UCoin，答错仍算签到成功（得 1 UCoin）。已签到时会自动跳过。

## 搜索

```bash
python dmhy.py search "鬼灭之刃"          # 关键字搜索
python dmhy.py search "关键词" -n 10      # 最多返回10条
python dmhy.py -v search "关键词"         # 详细日志
```

返回 JSON，每条结果包含：

| 字段 | 说明 |
|------|------|
| `category` | 作品类型（BDMV, BDRip, DVDISO, ...） |
| `title` | 标题 |
| `subtitle` | 副标题 / 促销说明 |
| `size` | 种子大小 |
| `survival` | 生存时间 |
| `seeders` | 种子数 |
| `leechers` | 下载中 |
| `completed` | 已完成下载 |
| `rating` | 评分 |
| `comments` | 评论数 |
| `details_url` | 详情页链接 |
| `download_url` | 种子下载直链（`.torrent` 文件） |

## 配置 (.env)

```env
DMHY_USERNAME=your_email@example.com
DMHY_PASSWORD=your_password
HTTP_PROXY=http://127.0.0.1:20170
HTTPS_PROXY=http://127.0.0.1:20170
```

成功登录后 `cookies.pkl` 自动更新。
> 四站统一的手动 cookie 方式见根 README「配置」节: 文件放 `data/cookies/` 或油猴一键发送。

## 依赖

python=3.11, requests, beautifulsoup4, lxml, python-dotenv
ddddocr, pytesseract, pillow（OCR 登录必需）
