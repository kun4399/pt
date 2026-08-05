# PT 站工具统一入口
# 用法: make <target> KW="关键词"
PY = conda run -n pt python

# azusa.wiki (登录 + 搜索)
azusa-search:      $(PY) sites/azusapt/azusa_login.py --search "$(KW)"

# tjupt.org (登录 / 海报OCR签到 / 搜索下载)
tjupt-login:       $(PY) sites/tjupt/tjupt_login.py
tjupt-sign:        $(PY) sites/tjupt/tjupt_sign.py
tjupt-search:      $(PY) sites/tjupt/tjupt_search.py "$(KW)"

# u2.dmhy.org (登录 / 签到 / 搜索)
dmhy-login:        $(PY) sites/dmhypt/login.py
dmhy-checkin:      $(PY) sites/dmhypt/dmhy.py checkin
dmhy-search:       $(PY) sites/dmhypt/dmhy.py search "$(KW)"

# pterclub.net (cookie 检查 / 搜索)
pterclub-check:    $(PY) sites/ptclub/pterclub.py check
pterclub-search:   $(PY) sites/ptclub/pterclub.py search "$(KW)"

# 示例: make azusa-search KW="汉化"
