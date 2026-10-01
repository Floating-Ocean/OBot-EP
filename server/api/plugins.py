"""插件清单路由。

工具首页、导航栏、以及「这个工具的上游数据目录还在不在」都从这一个接口取。
新增工具不需要改这里 —— 内容来自 `PluginRegistry`。
"""

from __future__ import annotations

from fastapi import APIRouter

from .deps import CurrentUser, Registry

router = APIRouter(tags=["plugins"])


@router.get("/plugins")
def list_plugins(registry: Registry, _user: CurrentUser) -> dict:
    """已加载的插件清单 + 每个插件的自检结果（需登录）。"""
    return {"plugins": registry.describe()}
