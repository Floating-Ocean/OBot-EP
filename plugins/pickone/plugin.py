"""PickOne 插件的装配：manifest、路由、启动钩子、版本号解析。

想抄一个插件，从这个文件开始 —— 它包含了插件与框架之间的全部接口。
"""

from __future__ import annotations

import logging
import re

from fastapi import FastAPI

from server import config as server_config
from server.plugin import BasePlugin, PluginManifest

from . import config
from .api import build_router
from .api.deps import STATE_KEY
from .store import PickOneStore
from .types import SUBMISSION_TYPES

logger = logging.getLogger("obot_ep")

# OBot-ACM 源码里 Pick-One 模块的版本号
_MODULE_VERSION_RE = re.compile(r'name="Pick-One",\s*version="([^"]+)"')

_MANIFEST = PluginManifest(
    slug=config.SLUG,
    name="PickOne 表情包",
    tag="表情包数据",
    icon="Grid",
    summary="维护「来只」表情包的图片描述、类别别名与点赞评论。",
    home="/pickone",
    order=10,
    submission_types=SUBMISSION_TYPES,
    accent={
        "tint": "rgba(158, 87, 114, 0.07)",
        "tint_strong": "rgba(158, 87, 114, 0.14)",
        "ink": "#764156",
        "track": "rgba(158, 87, 114, 0.16)",
        "glow": "rgba(158, 87, 114, 0.24)",
    },
)


class PickOnePlugin(BasePlugin):
    manifest = _MANIFEST

    def build_router(self):
        return build_router()

    # ---------- 生命周期 ----------

    def startup(self, app: FastAPI) -> None:
        """准备数据访问层。真实目录存不存在由 health() 汇报，不在这里阻塞启动。"""
        setattr(app.state, STATE_KEY, PickOneStore())
        logger.info("PickOne data dir  : %s", config.PICK_ONE_DIR)

    # ---------- 自检与版本 ----------

    def health(self) -> dict:
        """工具首页据此提示「数据目录不可用」。"""
        available = config.PICK_ONE_DIR.is_dir()
        return {
            "ok": available,
            "lib_dir": str(config.PICK_ONE_DIR),
        }

    def versions(self) -> dict[str, str | None]:
        """读 OBot-ACM 源码里 Pick-One 的模块版本号（读不到返回 None）。"""
        if config.MODULE_VERSION:
            return {"pickone": config.MODULE_VERSION}

        path = server_config.ACM_ROOT_DIR / "src" / "module" / "stuff" / "pick_one.py"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {"pickone": None}

        found = _MODULE_VERSION_RE.search(text)
        return {"pickone": found.group(1) if found else None}


PLUGIN = PickOnePlugin()
