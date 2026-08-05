"""跨站点共享常量: UA 与默认 header。

来源: azusapt/azusa_login.py L55-61, tjupt/tjupt_login.py L19-21,
       dmhypt/login.py L90, dmhypt/dmhy.py L66, ptclub/pterclub.py L75-76,
       azusa_login.py L27-31
"""

# azusa_login / tjupt_login (Chrome/120, X11)
UA_CHROME_X11 = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# dmhy login.py / dmhy.py (Chrome/120, Windows)
UA_CHROME_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# pterclub.py (Chrome/131, X11)
UA_CHROME_X11_131 = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# azusa_login 默认 header 集
DEFAULT_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
# dmhy 使用的精简 Accept(行为保持)
DEFAULT_ACCEPT_LANG = "zh-CN,zh;q=0.9,en;q=0.8"
DEFAULT_ACCEPT_ENCODING = "gzip, deflate, br"
