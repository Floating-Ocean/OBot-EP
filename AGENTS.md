# AGENTS.md

给在本仓库工作的 AI Agent（和人）看的说明书。**先读这个文件，再读代码。**

## 1. 这是什么

OBot-EP 是 [OBot-ACM](https://github.com/Floating-Ocean/OBot-ACM) 的 **Web 端维护工具集合**。
它不是单一工具，而是「框架 + 插件」：

|        | 是什么                            | 在哪                                            |
|--------|--------------------------------|-----------------------------------------------|
| **框架** | 认证、账号、提交单、审计日志、审核流程、插件注册表、前端托管 | `server/`、`web/src/api/`、`web/src/views/` 顶层  |
| **插件** | 一个工具的全部实现（数据模型、接口、页面）          | `plugins/<slug>/` + `web/src/plugins/<slug>/` |

**核心性质：新增一个工具不需要改框架里的任何文件。** 前后端各自自动发现：

- 后端 `server/plugin.py::discover_plugins()` 扫 `plugins/` 下的子包（`_` 开头跳过），读每个包的 `PLUGIN`
- 前端 `web/src/plugins/registry.js` 用 `import.meta.glob('./*/index.js')` 扫同级目录

想为加工具而改 `server/app.py` / `web/src/router/index.js` / `web/src/views/ToolHubView.vue` /
`web/src/layout/ToolShell.vue`，**说明方向错了** —— 这四个文件都已经由注册表驱动。

> **要写一个新工具 / 改一个插件 → 读 [`plugins/AGENTS.md`](plugins/AGENTS.md)。**
> 那份文件只在动插件时才需要读。

## 2. 目录地图

```
server/                     框架（不认识任何具体工具）
  app.py                    组装：装框架路由 + 挂插件路由 + 托管前端
  plugin.py                 BasePlugin / PluginManifest / PluginRegistry / discover_plugins
  inspect.py                自省 CLI：plugins / routes / check
  scaffold.py               新插件脚手架（模板在 plugins/_template/）
  errors.py                 StoreError / NotFoundError / ValidationError（已装好异常处理器）
  config.py                 框架级配置；repository.py 账号/提交单/审计日志
  schemas.py security.py ratelimit.py manage.py
  api/                      框架自带路由：auth / meta / plugins / admin
plugins/                    插件（每个子目录一个工具）
  pickone/                  现有唯一插件
  _template/                脚手架模板（不是插件，以 _ 开头所以不会被加载）
web/src/
  api/http.js core.js index.js   接口门面（框架 + 各插件，见 §5）
  plugins/registry.js       前端插件自动发现
  plugins/pickone/          插件前端：index.js manifest.js routes.js api.js views/ components/
  views/ToolHubView.vue     工具首页；views/admin/ 账号、日志、通用审核台
  router/index.js           框架路由 + 插件路由；layout/ToolShell.vue 导航栏
tests/                      每个文件都是可独立运行的脚本（不是 pytest）
check.ps1                   一条命令跑完全部验证
```

## 3. 铁律

1. **`server/` 里永远不要 import 任何 `plugins.*`。** 框架只认识抽象；
   需要新能力就加到 `server/plugin.py` 的扩展点（`startup` / `shutdown` / `health` / `versions`）。
2. **插件配置写在 `plugins/<slug>/config.py`**，不要往 `server/config.py` 里加具体工具的东西。
3. **插件的错误类型必须来自 `server/errors.py`** —— 核心只给这三个类型装了 400/404 处理器。
4. **每张提交单都要带 `plugin=<slug>`**，否则审核队列与下发会串到别的工具。
5. **slug 三处必须一致**：目录名、后端 `manifest.slug`、前端 `manifest.js` 的 `slug`。
   后端不一致启动就报错；前后端不一致会被 `server.inspect check` 报出来。
6. **`web/src/plugins/<slug>/index.js` 不要 import `@/api`**，用同目录下的 `./api`
   （`@/api` → registry → index.js 是循环依赖，在那里反向引用会读到还没建好的门面）。
   视图里用 `@/api` 没问题 —— 视图是路由懒加载的。
7. **日志与 CLI 输出一律 ASCII 英文**，中文只出现在给用户看的错误与页面文案里。
8. 只改要求改的东西。仓库里的注释是刻意写下的设计理由，不要顺手重构。

## 4. 命令

```powershell
.\check.ps1                  # 唯一的验证入口：ruff + PowerShell lint + 契约 + 三个测试 + 前端构建
.\check.ps1 -Fast            # 跳过前端构建（只改了后端时用）
.\check.ps1 -Verbose         # 每一步都打印完整输出

.\start.ps1                  # 启动（0.0.0.0:8000，局域网可访问）
.\dev.ps1                    # 开发：前端 5173 + 后端 8000，都绑回环

uv run python -m server.inspect plugins                  # 有哪些插件、接线对不对
uv run python -m server.inspect routes [--plugin <slug>] # 完整路由表（按框架/插件分组）
uv run python -m server.inspect check                    # 插件契约校验

uv run python -m server.scaffold <slug> --name "<名字>"   # 生成一个能跑的新插件骨架
uv run python -m server.manage list                      # 账号 CLI（passwd/create/role/...）
uv run ruff check .                                      # 只跑 Python lint
```

**改完任何东西都跑 `.\check.ps1`。** 前端改完必须重新构建 —— 后端直接托管 `web/dist`。

改 `.ps1` 时可以只跑 PowerShell 那一步：

```powershell
Import-Module PSScriptAnalyzer
Invoke-ScriptAnalyzer -Path . -Recurse -Settings .\PSScriptAnalyzerSettings.psd1
```

`PSScriptAnalyzerSettings.psd1` 里排除的规则都写明了原因（都是对交互式启动脚本不适用的）；
加新排除项请照样写清楚，别把整个规则集关掉。

## 5. 接口门面（只记这一条，细节在 plugins/AGENTS.md）

框架接口挂在 `api.*`（认证、`/api/admin/queue`、`/api/admin/review/*`、账号、日志）；
插件接口挂在 `api.<slug>.*`。**新代码统一用 `api.<slug>.*`** —— 平铺的 `api.方法名()` 是兼容层，
只有全站唯一的名字才会平铺出来；重名时自动退化成命名空间写法（不报错，只是少一个平铺别名）。

## 6. 需要更深的上下文时

| 你要做的事            | 读                                           |
|------------------|---------------------------------------------|
| 新增/修改一个插件（后端或前端） | [`plugins/AGENTS.md`](plugins/AGENTS.md)    |
| 看一个「完整长成什么样」的插件  | `plugins/pickone/`                          |
| 看一个「最小能跑」的插件     | `plugins/_template/`，或直接跑 `server.scaffold` |
| 配置项、部署、安全注意      | [`README.md`](README.md)                    |
