"""插件契约与注册表。

一个「工具」= 一个插件包（`plugins/<slug>/`）。核心只认识这里的抽象，
不 import 任何具体插件；`plugins/<slug>/__init__.py` 里的 `PLUGIN` 是唯一入口。

新增一个工具的最小步骤（详见 AGENTS.md）：

    1. 建 `plugins/<slug>/__init__.py`，里面写 `from .plugin import PLUGIN`
    2. 建 `plugins/<slug>/plugin.py`，继承 BasePlugin，给出 manifest 并实现 build_router()
    3. 前端建 `web/src/plugins/<slug>/index.js` 导出 `{manifest, routes, api}`

发现是自动的：扫 `plugins/` 下所有子包，读它们的 `PLUGIN`，按 manifest.order 排序。
核心任何地方都不需要维护插件清单，这正是「加工具不用改框架」的关键。
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, status

from . import config

logger = logging.getLogger("obot_ep")


@dataclass(frozen=True)
class PluginManifest:
    """插件对外的自我介绍。前端工具首页与导航栏直接渲染这些字段。"""

    slug: str
    """URL 与包名的一部分：`/api/plugins/<slug>`。只用小写字母、数字与短横线。"""

    name: str
    """中文显示名，例如「PickOne 表情包」。"""

    tag: str = ""
    """首页卡片上的小标签，例如「表情包数据」。"""

    icon: str = "Grid"
    """Element Plus 图标组件名（前端 main.js 已全局注册全部图标）。"""

    summary: str = ""
    """一句话说明这个工具能改什么。"""

    accent: dict[str, str] = field(default_factory=dict)
    """卡片配色：tint / tint_strong / ink / track / glow。留空则用默认青色系。"""

    order: int = 100
    """首页排序，越小越靠前。"""

    home: str = ""
    """工具入口路径（前端 `home` 的缺省值），例如 `/pickone`。"""

    submission_types: tuple[str, ...] = ()
    """本插件用到的提交类型（仅供展示 / 前端参考）。

    真正让核心认识这些类型的是插件在自己的 `__init__.py` 里调的
    `server.repository.register_submission_types(slug, labels)` —— 那里才带中文名。
    """

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "tag": self.tag,
            "icon": self.icon,
            "summary": self.summary,
            "accent": dict(self.accent),
            "order": self.order,
            "home": self.home,
            "submission_types": list(self.submission_types),
        }


class BasePlugin(ABC):
    """所有插件的基类。

    子类只需做两件事：给出 `manifest`、实现 `build_router()`。
    需要自己的运行时状态（数据目录、缓存、快照）就在 `startup()` 里准备，
    并挂在 `app.state` 上，由插件自己的 deps 取用 —— 核心不碰这些状态。
    """

    manifest: PluginManifest

    def __init__(self) -> None:
        self.router: APIRouter = self.build_router()

    # ---------- 身份 ----------

    @property
    def slug(self) -> str:
        return self.manifest.slug

    @property
    def api_prefix(self) -> str:
        """插件所有接口的挂载前缀。插件内部写相对路径即可。"""
        return f"{config.API_PREFIX}/plugins/{self.slug}"

    # ---------- 生命周期 ----------

    @abstractmethod
    def build_router(self) -> APIRouter:
        """返回本插件的路由。路径相对于 `api_prefix`。"""

    def startup(self, app: FastAPI) -> None:
        """应用启动钩子：建目录、加载数据、把状态挂到 app.state。"""

    def shutdown(self) -> None:
        """应用关闭钩子：释放插件持有的资源。"""

    # ---------- 可选扩展点 ----------

    def health(self) -> dict[str, Any]:
        """插件自检信息，会合并进 `GET /api/plugins` 的返回里。

        典型用法是回报「上游数据目录在不在」。不要在这里做重活：这个接口
        每次打开工具首页都会被调用。
        """
        return {}

    def versions(self) -> dict[str, str | None]:
        """插件回报自己所维护的上游模块版本号，合并进 `/api/meta/*`。"""
        return {}


class PluginRegistry:
    """已加载插件的只读集合。"""

    def __init__(self, plugins: Iterable[BasePlugin]) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        for plugin in plugins:
            slug = plugin.slug
            if slug in self._plugins:
                raise ValueError(f"插件 slug 重复: {slug}")
            self._plugins[slug] = plugin

    def __iter__(self) -> Iterator[BasePlugin]:
        return iter(self._plugins.values())

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, slug: object) -> bool:
        return slug in self._plugins

    def get(self, slug: str) -> BasePlugin:
        plugin = self._plugins.get(slug)
        if plugin is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"插件不存在: {slug}"
            )
        return plugin

    def manifests(self) -> list[dict[str, Any]]:
        return [plugin.manifest.to_dict() for plugin in self._plugins.values()]

    def describe(self) -> list[dict[str, Any]]:
        """清单 + 各插件的自检结果，供 `GET /api/plugins` 使用。"""
        described: list[dict[str, Any]] = []
        for plugin in self._plugins.values():
            item = plugin.manifest.to_dict()
            try:
                item["health"] = plugin.health()
            except Exception as error:  # 单个插件坏掉不该让首页 500
                logger.warning("plugin %s health check failed: %s", plugin.slug, error)
                item["health"] = {"ok": False}
            described.append(item)
        return described

    def versions(self) -> dict[str, str | None]:
        merged: dict[str, str | None] = {}
        for plugin in self._plugins.values():
            merged.update(plugin.versions())
        return merged


def discover_plugins() -> list[BasePlugin]:
    """扫描 `plugins/` 目录并实例化插件。

    约定：`plugins/<name>/__init__.py` 必须导出 `PLUGIN`（一个 BasePlugin 实例）。
    名以 `_` 开头或不是包的目录会被跳过，因此放草稿、文档、测试数据都不会被加载。
    """
    root = config.PLUGINS_DIR
    if not root.is_dir():
        logger.warning("plugins directory not found: %s", root)
        return []

    parent = str(root.parent)
    if parent not in sys.path:
        # 插件以顶层包（plugins.<name>）导入，所以仓库根必须在 sys.path 上。
        # 从别的目录启动（例如系统服务）时 cwd 不一定是仓库根，这里补上。
        sys.path.insert(0, parent)

    discovered: list[BasePlugin] = []
    for info in sorted(pkgutil.iter_modules([str(root)]), key=lambda item: item.name):
        if info.name.startswith("_") or not info.ispkg:
            continue

        module = importlib.import_module(f"{root.name}.{info.name}")
        plugin = getattr(module, "PLUGIN", None)
        if plugin is None:
            logger.warning("plugins/%s has no PLUGIN, skipped", info.name)
            continue
        if not isinstance(plugin, BasePlugin):
            raise TypeError(f"plugins/{info.name}.PLUGIN must be a BasePlugin instance")
        if plugin.slug != info.name:
            # slug 决定 URL 与前端目录名，和包名不一致只会让人找错地方
            raise ValueError(
                f"plugins/{info.name} declares slug {plugin.slug!r}; "
                "the package name and the manifest slug must match"
            )
        discovered.append(plugin)

    discovered.sort(key=lambda item: (item.manifest.order, item.slug))
    logger.info(
        "loaded %d plugin(s): %s",
        len(discovered),
        ", ".join(plugin.slug for plugin in discovered) or "-",
    )
    return discovered
