"""@@NAME@@ 插件的装配：manifest、路由、启动钩子、自检。

想抄一个插件，从这个文件开始 —— 它包含了插件与框架之间的全部接口。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, FastAPI

from server.plugin import BasePlugin, PluginManifest

from . import config
from .api import build_router
from .api.deps import STATE_KEY
from .store import ItemStore
from .types import SUBMISSION_TYPES

logger = logging.getLogger("obot_ep")

_MANIFEST = PluginManifest(
    slug=config.SLUG,
    name="@@NAME@@",
    tag="@@TAG@@",
    # Element Plus 图标名，前端 main.js 已全局注册；挑一个合适的即可
    icon="Grid",
    summary="TODO(@@SLUG@@): 一句话说明这个工具能改什么。",
    home="/@@SLUG@@",
    order=100,
    submission_types=SUBMISSION_TYPES,
    accent={
        "tint": "rgba(56, 189, 214, 0.10)",
        "tint_strong": "rgba(56, 189, 214, 0.26)",
        "ink": "#0f6f85",
        "track": "rgba(56, 189, 214, 0.2)",
        "glow": "rgba(56, 189, 214, 0.3)",
    },
)


class @@CLASS@@Plugin(BasePlugin):
    manifest = _MANIFEST

    def build_router(self) -> APIRouter:
        return build_router()

    # ---------- 生命周期 ----------

    def startup(self, app: FastAPI) -> None:
        """准备本插件要用的运行时状态，挂在 app.state 上由自己的 deps 取用。"""
        setattr(app.state, STATE_KEY, ItemStore())
        logger.info("%s data dir  : %s", config.SLUG, config.DATA_DIR)

    # ---------- 自检与版本 ----------

    def health(self) -> dict:
        """工具首页据此提示「本工具当前是否可用」。

        骨架的数据目录是按需创建的，所以只要父目录在就算就绪；换成真实数据文件后，
        这里应该回报「上游文件在不在」，让首页能给出「数据目录不可用」的提示。
        """
        return {"ok": True, "dir": str(config.DATA_DIR)}

    def versions(self) -> dict[str, str | None]:
        """需要显示上游模块版本号时在这里返回，例如 {"mytool": "v1.2.3"}。"""
        return {}


PLUGIN = @@CLASS@@Plugin()
