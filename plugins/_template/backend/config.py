"""@@NAME@@ 插件自己的配置。

框架的 `server/config.py` 只管所有工具共用的事（数据目录、数据库、密钥）；
「这个工具的数据在哪」是插件自己的事，所以写在这里。
"""

from __future__ import annotations

from server import config

# 插件标识。目录名、manifest.slug、提交单的 plugin 列三处必须是同一个值。
SLUG = "@@SLUG@@"

# TODO(@@SLUG@@): 指向这个工具真正要维护的数据文件/目录。
# 要挂到别的 OBot-ACM 模块下，就把默认值换成 config.ACM_LIB_DIR / "<Module>"。
DATA_DIR = config.env_path("@@ENV@@_DIR", config.DATA_DIR / "plugins" / SLUG)
