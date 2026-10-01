"""框架级路由的聚合入口。

只有「与具体工具无关」的路由在这里：认证、元信息、插件清单、账号/日志/审核。
插件路由由 `server.app` 按 `plugins/<slug>/` 自动挂载，不经过这个模块。
"""

from . import admin, auth, meta, plugins

__all__ = ["admin", "auth", "meta", "plugins"]
