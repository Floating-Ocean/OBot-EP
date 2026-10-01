"""@@NAME@@ 自己的路由依赖：从 app.state 取本插件启动时放好的 Store。

框架的 `server/api/deps.py` 不 import 任何插件，所以「怎么拿到自己的 Store」
是插件自己的事 —— 这是插件与核心之间唯一需要约定的那点间接。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from ..store import ItemStore

# app.state 上的属性名。只在 plugin.startup() 与这里出现，改名要一起改。
STATE_KEY = "@@SLUG@@_store"


def get_store(request: Request) -> ItemStore:
    store = getattr(request.app.state, STATE_KEY, None)
    if store is None:
        # 只可能是 startup() 里没放进来（插件启动失败）。这属于部署问题，
        # 明确报 503 比让请求炸成 500 更容易查。
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="@@NAME@@ 插件未就绪，请查看服务端日志",
        )
    return store


Store = Annotated[ItemStore, Depends(get_store)]
