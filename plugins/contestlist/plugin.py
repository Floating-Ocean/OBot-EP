"""算法竞赛列表插件的装配：manifest、路由、启动钩子、自检。

想抄一个插件，从这个文件开始 —— 它包含了插件与框架之间的全部接口。
"""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, FastAPI

from server import config as server_config
from server.plugin import BasePlugin, PluginManifest

from . import config
from .api import build_router
from .api.deps import STATE_KEY
from .store import ContestStore
from .types import SUBMISSION_TYPES

logger = logging.getLogger("obot_ep")

# OBot-ACM 源码里 Contest-List-Renderer 模块的版本号
_MODULE_VERSION_RE = re.compile(r'name="Contest-List-Renderer",\s*version="([^"]+)"')

_MANIFEST = PluginManifest(
    slug=config.SLUG,
    name="算法竞赛列表",
    tag="算法竞赛",
    icon="Trophy",
    summary="维护手动录入的算法竞赛列表，通常为 XCPC 等比赛。",
    home="/contestlist",
    order=20,
    submission_types=SUBMISSION_TYPES,
    accent={
        "tint": "rgba(124, 143, 79, 0.07)",
        "tint_strong": "rgba(124, 143, 79, 0.14)",
        "ink": "#5d6b3b",
        "track": "rgba(124, 143, 79, 0.16)",
        "glow": "rgba(124, 143, 79, 0.24)",
    },
)


class ContestListPlugin(BasePlugin):
    manifest = _MANIFEST

    def build_router(self) -> APIRouter:
        return build_router()

    # ---------- 生命周期 ----------

    def startup(self, app: FastAPI) -> None:
        """准备本插件要用的运行时状态，挂在 app.state 上由自己的 deps 取用。"""
        setattr(app.state, STATE_KEY, ContestStore())
        logger.info("%s data file : %s", config.SLUG, config.DATA_PATH)

    # ---------- 自检与版本 ----------

    def health(self) -> dict:
        """工具首页据此提示「本工具当前是否可用」。

        `manual_contests.json` 在 OBot-ACM 的 .gitignore 里，所以新环境里
        文件可能还不存在（Bot 第一次导入比赛时才创建）。目录在就算就绪 ——
        下发本身会原子地创建它。
        """
        available = config.DATA_PATH.is_file() or config.CONTEST_DIR.is_dir()
        return {
            "ok": available,
            "data_path": str(config.DATA_PATH),
            "file": config.DATA_PATH.is_file(),
        }

    def versions(self) -> dict[str, str | None]:
        """读 OBot-ACM 源码里 Contest-List-Renderer 的模块版本号（读不到返回 None）。"""
        if config.MODULE_VERSION:
            return {"contestlist": config.MODULE_VERSION}

        path = server_config.ACM_ROOT_DIR / "src" / "module" / "cp" / "contest_manual.py"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {"contestlist": None}

        found = _MODULE_VERSION_RE.search(text)
        return {"contestlist": found.group(1) if found else None}


PLUGIN = ContestListPlugin()
