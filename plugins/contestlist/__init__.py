"""算法竞赛列表插件：维护 OBot-ACM 里手动录入的比赛列表。

导入本包即完成两件事：
  1. `PLUGIN` 被核心发现（见 server/plugin.py）；
  2. 提交类型注册进框架，审核队列才知道 `type` 该显示成什么中文名。
"""

from __future__ import annotations

from server.repository import register_submission_types

from .plugin import PLUGIN
from .types import TYPE_LABELS

# 注册发生在 import 时，早于任何请求；重复 import 由 Python 的模块缓存保证只跑一次。
register_submission_types(PLUGIN.slug, TYPE_LABELS)

__all__ = ["PLUGIN"]
