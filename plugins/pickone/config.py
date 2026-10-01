"""PickOne 插件自己的配置。

核心的 `server/config.py` 只管「数据目录、数据库、密钥」这类所有工具共用的事；
「Pick-One 的数据在哪」是插件的事，所以放这里。
"""

from __future__ import annotations

import os

from server import config

# 插件标识。目录名、manifest.slug、提交单的 plugin 列三处必须是同一个值。
SLUG = "pickone"

# Pick-One 模块目录（config.json / parser.json / *.gif 都在这里）
PICK_ONE_DIR = config.env_path("OBOT_PICK_ONE_DIR", config.ACM_LIB_DIR / "Pick-One")

# 覆盖 OBot-ACM 版本号里的 PickOne 模块段（不放源码树时可以用）
MODULE_VERSION = os.environ.get("OBOT_PICKONE_VERSION", "").strip()
