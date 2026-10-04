"""算法竞赛列表插件自己的配置。

核心的 `server/config.py` 只管「数据目录、数据库、密钥」这类所有工具共用的事；
「手动维护的比赛列表在哪」是这个工具的事，所以放这里。
"""

from __future__ import annotations

from server import config

# 插件标识。目录名、manifest.slug、提交单的 plugin 列三处必须是同一个值。
SLUG = "contestlist"

# OBot-ACM 的 Contest-List-Renderer 模块目录，手动维护的比赛列表就在它下面。
# 这个文件 Bot（/导入比赛 指令）也会写，所以下发时必须做冲突检测。
CONTEST_DIR = config.ACM_LIB_DIR / "Contest-List-Renderer"

# 比赛列表数据文件：整份文件是一个 JSON 数组，元素形状见 store.py。
DATA_PATH = config.env_path("OBOT_CONTESTLIST_PATH", CONTEST_DIR / "manual_contests.json")

# 覆盖 OBot-ACM 版本号里的 Contest-List-Renderer 模块段（不放源码树时可以用）
MODULE_VERSION = ""
