# PT 站工具统一入口
# 用法: make <target> KW="关键词"
PY = conda run -n pt python

# azusa.wiki (登录 + 搜索)
azusa-search:
	$(PY) sites/azusapt/azusa_login.py --search "$(KW)"

# tjupt.org (登录 / 海报OCR签到 / 搜索下载)
tjupt-login:
	$(PY) sites/tjupt/tjupt_login.py
tjupt-sign:
	$(PY) sites/tjupt/tjupt_sign.py
tjupt-search:
	$(PY) sites/tjupt/tjupt_search.py "$(KW)"

# u2.dmhy.org (登录 / 签到 / 搜索)
dmhy-login:
	$(PY) sites/dmhypt/login.py
dmhy-checkin:
	$(PY) sites/dmhypt/dmhy.py checkin
dmhy-search:
	$(PY) sites/dmhypt/dmhy.py search "$(KW)"

# pterclub.net (cookie 检查 / 搜索)
pterclub-check:
	$(PY) sites/ptclub/pterclub.py check
pterclub-search:
	$(PY) sites/ptclub/pterclub.py search "$(KW)"

# 统一入口 (默认全站搜索 / 指定站点 / 登录前预检)
pt-search:
	$(PY) pt_search.py "$(KW)"
pt-search-site:
	$(PY) pt_search.py "$(KW)" --site "$(SITE)"
pt-check:
	$(PY) pt_search.py --check

# 统一签到 (默认四站 / 指定站点 / JSON 输出)
pt-checkin:
	$(PY) pt_checkin.py
pt-checkin-site:
	$(PY) pt_checkin.py --site "$(SITE)"
pt-checkin-json:
	$(PY) pt_checkin.py --json

# cookie 接收服务 (油猴脚本发送 cookie 的 HTTP 服务)
cookie-server:
	$(PY) pt_cookie_server.py

# 示例: make azusa-search KW="汉化" / make pt-search KW="4K" / make pt-checkin
