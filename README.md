# OBot-EP

Data maintainance platform online for OBot's ACM.

[OBot-ACM](https://github.com/Floating-Ocean/OBot-ACM) 的 **Web 端维护工具集合**，用于公开维护各模块的数据。


## 环境要求

NodeJS >= 24.0

低版本 NodeJS 可能导致构建出来的网站无法正常使用。

## 工具列表


### PickOne（`/pickone`）· 表情包数据

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


## 快速开始


### 1. 一键启动

```bash
.\start.ps1
```

### 2. 调试
```bash
.\dev.ps1
```


## 手动构建


### 1. 后端

```bash
uv sync
uv run uvicorn server.app:app --reload --port 8000
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


## 配置项

可通过环境变量覆盖默认配置。

| 变量                       | 默认值                      | 说明                             |
|--------------------------|--------------------------|--------------------------------|
| `OBOT_ACM_LIB_DIR`       | `../OBot-ACM/lib`        | OBot-ACM 的 `lib` 目录            |
| `OBOT_PICK_ONE_DIR`      | `<lib>/Pick-One`         | Pick-One 数据目录                  |
| `OBOT_EP_DATA_DIR`       | `./data`                 | 本地数据库与缩略图缓存                    |
| `OBOT_EP_DB_PATH`        | `<data>/obot_ep.sqlite3` | SQLite 文件                      |
| `OBOT_EP_SECRET`         | 随机                       | 会话签名密钥。**生产环境必须固定**，否则重启后所有人掉线 |
| `OBOT_EP_SESSION_TTL`    | `2592000`                | 会话有效期（秒），默认 30 天               |
| `OBOT_EP_ADMIN_USER`     | `admin`                  | 初始管理员用户名                       |
| `OBOT_EP_ADMIN_PASSWORD` | 随机                       | 初始管理员密码，留空则随机生成并打印             |
| `OBOT_EP_ALLOW_REGISTER` | `1`                      | 是否允许自助注册（注册后仅能提交，不能审核）         |
| `OBOT_EP_FRONTEND_DIST`  | `./web/dist`             | 前端构建产物目录                       |
| `OBOT_EP_API`            | `http://127.0.0.1:8000`  | Vite dev server 代理的后端地址        |
| `OBOT_EP_WEB_PORT`       | `5173`                   | Vite dev server 端口             |
