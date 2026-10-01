"""OBot-EP 插件包根目录。

每个子目录是一个工具（插件），`__init__.py` 里必须导出 `PLUGIN`。
核心通过 `server.plugin.discover_plugins()` 自动扫描这里，不需要任何注册表。
"""
