"""OBot-EP 后端包。

启动：`uv run uvicorn server.app:app --reload --port 8000`

`server/` 是**框架**（认证、账号、提交单、审计日志、插件注册表、前端托管）；
每个工具是 `plugins/<slug>/` 下的一个插件，由 server.plugin 自动发现。
新增工具不需要改这个包里的任何文件 —— 见仓库根目录的 AGENTS.md。
"""

__version__ = "0.2.0"
