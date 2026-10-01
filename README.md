# OBot-EP

Data maintainance platform online for OBot's ACM.

[OBot-ACM](https://github.com/Floating-Ocean/OBot-ACM) 的 **Web 端维护工具集合**，用于公开维护各模块的数据。


## 架构

项目是**插件的集合**，前后端各自**自动发现**插件。

```
server/                      框架：认证、账号、提交单、审计日志、审核流程、插件注册表、前端托管
plugins/<slug>/              一个工具的全部后端实现（数据模型 + 接口）
web/src/plugins/<slug>/      同一个工具的前端实现（manifest + 路由 + 页面）
```


## 环境要求

NodeJS >= 24.0

低版本 NodeJS 可能导致构建出来的网站无法正常使用。

## 工具列表


### PickOne（`/pickone`）· 表情包数据

代码：[`plugins/pickone/`](plugins/pickone/) + [`web/src/plugins/pickone/`](web/src/plugins/pickone/)

| 能改什么       | 落到哪里                                      |
|------------|-------------------------------------------|
| 图片描述文本     | `<类别>/parser.json` 的 `ocr_text`           |
| 图片点赞数 / 评论 | `<类别>/parser.json` 的 `likes` / `comments` |
| 类别显示名与别名列表 | `config.json` 的 `id` / `key`              |
| 新增类别       | `config.json` + 新建类别目录                    |

工作流：**注册/登录 → 提交修改 → 管理员审核 → 一键下发**。


## 技术栈

- 后端：FastAPI + Uvicorn，SQLite（标准库 `sqlite3`）存账号与提交单，Pillow 生成缩略图
- 前端：Vue 3 + Element Plus + Vue Router + Vite
- 全站需要登录才能浏览；密码用 PBKDF2-HMAC-SHA256 存摘要，会话是无状态 HMAC 签名 Cookie
- 插件隔离：提交单带 `plugin` 列，接口挂 `/api/plugins/<slug>/`，工具之间互不干扰


## 快速开始


### 1. 一键启动

```bash
.\start.ps1            # 监听 0.0.0.0，局域网内可直接访问 http://<本机IP>:8000
.\start.ps1 -Local     # 只监听 127.0.0.1，仅本机可用
```

### 2. 调试
```bash
.\dev.ps1                        # 前端 5173 + 后端 8000，都只绑回环
.\dev.ps1 -BindAddress 0.0.0.0   # 把开发预览也暴露到局域网（仅限受信任内网）
```


## 手动构建


### 1. 后端

```bash
uv sync
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000   # 仅本机
uv run uvicorn server.app:app --host 0.0.0.0 --port 8000     # 局域网可访问
# 也可以直接：uv run python app.py --host 0.0.0.0 --port 8000
```

首次启动会创建管理员账号，**初始密码打印在启动日志里**。
想固定密码可以设环境变量 `OBOT_EP_ADMIN_PASSWORD`。登录后请在右上角改密码。


### 重置管理员密码

```bash
uv run python -m server.manage list                    # 看有哪些账号
uv run python -m server.manage passwd --user admin     # 交互式改密码
uv run python -m server.manage passwd --user admin --password '新密码'
uv run python -m server.manage create --user alice --password secret123 --role admin
uv run python -m server.manage role --user alice --role admin
uv run python -m server.manage disable --user alice
```


### 2. 前端

```bash
cd web
npm ci
npm run build
```


## 开发：加一个新工具

一条命令生成一个能跑的骨架（后端 + 前端 + 首页卡片 + 审核台），然后只改领域逻辑：

```bash
uv run python -m server.scaffold mytool --name "My Tool" --tag "数据维护"
```

生成完它会**自动跑一遍插件契约检查**，并列出还剩哪些 `TODO(mytool)`。
不需要改框架里的任何文件 —— 插件是自动发现的。

自省命令（想知道「现在有什么、接口挂在哪」时用）：

```bash
uv run python -m server.inspect plugins                  # 插件清单 + 接线检查
uv run python -m server.inspect routes [--plugin <slug>] # 完整路由表
uv run python -m server.inspect check                    # 插件契约校验
```

完整约定见 [AGENTS.md](AGENTS.md)（总览）与 [plugins/AGENTS.md](plugins/AGENTS.md)（写插件）。


## 验证

改完任何东西都跑这一条：

```bash
.\check.ps1          # ruff + PowerShell lint + 插件契约 + 脚手架自检 + 后端测试 + 安全测试 + 前端构建
.\check.ps1 -Fast    # 跳过前端构建
.\check.ps1 -Verbose # 每一步都打印完整输出
```


## 配置项

可通过环境变量覆盖默认配置。

框架级（`server/config.py`）：

| 变量                       | 默认值                      | 说明                                       |
|--------------------------|--------------------------|------------------------------------------|
| `OBOT_ACM_LIB_DIR`       | `../OBot-ACM/lib`        | OBot-ACM 的 `lib` 目录（插件的数据目录挂在它下面）        |
| `OBOT_ACM_ROOT_DIR`      | `../OBot-ACM`            | OBot-ACM 源码根目录，用来读它的版本号                  |
| `OBOT_EP_DATA_DIR`       | `./data`                 | 本地数据库与缩略图缓存                              |
| `OBOT_EP_DB_PATH`        | `<data>/obot_ep.sqlite3` | SQLite 文件                                |
| `OBOT_EP_LEGACY_PLUGIN`  | `pickone`                | 升级老库时，插件化之前的提交单归属给哪个插件                   |
| `OBOT_EP_SECRET`         | 随机                       | 会话签名密钥。**生产环境必须固定**，否则重启后所有人掉线           |
| `OBOT_EP_SESSION_TTL`    | `2592000`                | 会话有效期（秒），默认 30 天                         |
| `OBOT_EP_COOKIE_SECURE`  | `0`                      | 设 `1` 时会话 Cookie 只走 HTTPS（挂在域名/反代后面务必打开） |
| `OBOT_EP_ADMIN_USER`     | `admin`                  | 初始管理员用户名                                 |
| `OBOT_EP_ADMIN_PASSWORD` | 随机                       | 初始管理员密码，留空则随机生成并打印                       |
| `OBOT_EP_ALLOW_REGISTER` | `1`                      | 是否允许自助注册（注册后仅能提交，不能审核）                   |
| `OBOT_EP_FRONTEND_DIST`  | `./web/dist`             | 前端构建产物目录                                 |
| `OBOT_EP_API`            | `http://127.0.0.1:8000`  | Vite dev server 代理的后端地址                  |
| `OBOT_EP_WEB_PORT`       | `5173`                   | Vite dev server 端口                       |

插件级（`plugins/<slug>/config.py`，加新工具时在这里加自己的）：

| 变量                  | 默认值              | 说明                    |
|---------------------|------------------|-----------------------|
| `OBOT_PICK_ONE_DIR` | `<lib>/Pick-One` | Pick-One 数据目录（PickOne 插件） |

限速与缩略图相关的可调项（一般不用改）：

| 变量                             | 默认值        | 说明                                                    |
|--------------------------------|------------|-------------------------------------------------------|
| `OBOT_EP_LOGIN_MAX`            | `10`       | 每窗口允许的登录尝试次数（按 IP 和账号各算一份），`0` = 不限速                  |
| `OBOT_EP_LOGIN_WINDOW`         | `300`      | 登录限速窗口（秒）                                             |
| `OBOT_EP_REGISTER_MAX`         | `20`       | 每窗口允许的注册次数（按 IP）                                      |
| `OBOT_EP_REGISTER_WINDOW`      | `3600`     | 注册限速窗口（秒）                                             |
| `OBOT_EP_PASSWORD_MAX`         | `10`       | 每窗口允许的改密次数（按账号）                                       |
| `OBOT_EP_PASSWORD_WINDOW`      | `900`      | 改密限速窗口（秒）                                             |
| `OBOT_EP_AUTH_GLOBAL_MAX`      | `60`       | 全站认证请求上限（不限来源），兜底防并发爆破                                |
| `OBOT_EP_AUTH_GLOBAL_WINDOW`   | `60`       | 全站认证窗口（秒）                                             |
| `OBOT_EP_MAX_BODY_BYTES`       | `262144`   | 单个请求体上限（字节），超限直接 413                                  |
| `OBOT_EP_TRUSTED_ORIGINS`      | 空          | 额外信任的写请求来源（逗号分隔），仅当前面有改写 Host 的代理时需要                  |
| `OBOT_EP_TRUST_PROXY`          | `0`        | 设 `1` 时按 `X-Real-IP`/`X-Forwarded-For` 区分限速对象（反代部署必开） |
| `OBOT_EP_TRUSTED_PROXY_IPS`    | 空          | 代理自身的地址（逗号分隔），用于从 `X-Forwarded-For` 里跳过它们             |
| `OBOT_EP_ENABLE_DOCS`          | `0`        | 设 `1` 才开放 `/docs`、`/redoc`、`/openapi.json`（无需登录，默认关闭） |
| `OBOT_EP_BIND_HOST`            | 空          | 进程实际绑定的地址，由启动脚本写入；仅用于启动时判断是否需要告警                      |
| `OBOT_EP_THUMB_MAX_FILE_BYTES` | `33554432` | 生成缩略图的源文件大小上限（字节）                                     |
| `OBOT_EP_THUMB_MAX_PIXELS`     | `40000000` | Pillow 允许解码的最大像素数                                     |
