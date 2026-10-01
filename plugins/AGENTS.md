# plugins/AGENTS.md

只在**写或改一个插件**时才需要读这个文件。仓库总览在 [`../AGENTS.md`](../AGENTS.md)。

**先跑脚手架，再读生成的代码 —— 那比读这份文档快。**

```powershell
uv run python -m server.scaffold mytool --name "My Tool" --tag "数据维护"
```

它生成 `plugins/mytool/`（后端）+ `web/src/plugins/mytool/`（前端），**生成完立刻自检**
（插件契约 + 列出手上还剩的 `TODO(mytool)`）。骨架是能跑的：首页会出现卡片、能提交、
能在审核台审核下发。你要做的只是把领域逻辑换掉。

> 与其读文档，不如读代码：`plugins/_template/` 是「最小能跑」，`plugins/pickone/` 是
> 「长完整了长什么样」（含冲突检测、缩略图、批量提交）。

## 1. 一个插件由什么组成

```
plugins/<slug>/                       后端
  __init__.py        导出 PLUGIN + 注册提交类型（这一行 import 即副作用，是刻意的）
  plugin.py          ★ 插件的门面：manifest + build_router() + startup/health/versions
  config.py          SLUG 与本工具自己的配置
  types.py           提交类型常量 + 中文名
  schemas.py         提交请求模型
  store.py           数据读写（领域逻辑）
  api/deps.py        从 app.state 取自己的 Store
  api/__init__.py    把下面的路由合成一个
  api/items.py       用户侧：浏览 + 提交 + 撤回
  api/admin.py       管理侧：apply / apply-preview / overview

web/src/plugins/<slug>/               前端
  index.js           ★ 默认导出 { manifest, routes, api, stat? }
  manifest.js        名称、图标、配色、导航项
  routes.js          路由（每条 path 以 manifest.home 开头）
  api.js             接口方法表
  views/ components/ 页面
```

`★` 的两个文件是**契约**，其余可以自由发挥。

## 2. 后端契约

`BasePlugin`（`server/plugin.py`）只要求两样东西：

```python
class MyToolPlugin(BasePlugin):
    manifest = PluginManifest(...)          # 必填：自我介绍
    def build_router(self) -> APIRouter:    # 必填：本插件的路由
        ...
```

可选扩展点（按需实现，基类里有空实现）：

| 方法                   | 作用                                                     |
|----------------------|--------------------------------------------------------|
| `startup(app)`       | 启动钩子。把插件状态挂到 `app.state`，由自己的 `api/deps.py` 取用         |
| `shutdown()`         | 关闭钩子                                                   |
| `health() -> dict`   | 自检，合并进 `GET /api/plugins`；`{"ok": False}` 会让首页卡片显示成不可用 |
| `versions() -> dict` | 上游模块版本号，合并进 `/api/meta/*` 的版本标签                        |

`PluginManifest` 字段：`slug` / `name` / `tag` / `icon` / `summary` / `home` / `order` /
`accent` / `submission_types`。前端的 `manifest.js` 是同一份数据的前端副本 —— **两边 slug 必须一致**。

### 路由挂在哪

插件的路由自动挂到 `/api/plugins/<slug>` 下，**`build_router()` 里写相对路径**：

```python
router = APIRouter(prefix="/items", tags=["mytool-items"])   # → /api/plugins/mytool/items
```

写过 `/api/...` 会被 `server.inspect check` 报错（会变成 `/api/plugins/mytool/api/...`）。

### 提交类型

框架只存 `type` 字符串。插件在 `__init__.py` 里注册自己的词汇表：

```python
register_submission_types(PLUGIN.slug, TYPE_LABELS)   # 建议在 __init__.py 顶部调用
```

`server.inspect check` 会比对它与 `manifest.submission_types` 是否一致。

### 不要自己实现的东西

审核流程是**框架能力**，插件只要把改动写成一条提交单：

| 框架已经提供                                                          | 插件不要重复写        |
|-----------------------------------------------------------------|----------------|
| `GET /api/admin/queue?plugin=<slug>`                            | 审核队列           |
| `POST /api/admin/review/{id}`、`/review/batch`、`/unreview/{id}`  | 批准 / 驳回 / 撤回审核 |
| `GET /api/admin/users*`、`/api/admin/logs`、`/api/admin/overview` | 账号、审计日志、全站计数   |
| 通用审核台页面 `web/src/views/admin/PluginReviewView.vue`              | 审核界面           |

插件只提供三个**约定路径**，通用审核台就认它：

```
GET  /api/plugins/<slug>/admin/overview       计数 + lib_available
GET  /api/plugins/<slug>/admin/apply/preview  下发前 dry-run
POST /api/plugins/<slug>/admin/apply          真正写盘
```

## 3. 提交单模型

写提交单时记住三件事：

```python
repo.upsert_submission(
    plugin=config.SLUG,   # 必填。少了它，审核队列会串到别的工具
    type=TYPE_TEXT,       # 必须是注册过的类型
    img_key=payload.key,  # 「这条改动挂在哪个资源上」
    target="",            # 同一个资源下的不同字段用 target 区分；只有一个字段就留空
    submitted_value=...,
    base_value=...,       # 提交时看到的值 —— 应用时靠它检测冲突
    author_id=user.id,
)
```

生命周期：

```
pending --审核通过--> approved --一键应用--> applied
   \--审核驳回--> rejected
approved --应用时发现磁盘原值被改--> conflict --裁定--> approved / rejected
```

同一 `(plugin, type, img_key, target, author_id)` 只允许一条「在途」提交，反复改同一字段是覆盖
而不是刷队列。**审核与应用是两个动作**：审核只排队，管理员点「一键下发」才写盘。

> 冲突检测不是必须的。数据文件如果只有这个工具在写，直接覆盖就行；如果 Bot 也写同一个文件，
> 就该在 apply 时比对 `base_value` 与磁盘现值，不一致挂成 `conflict` ——
> 完整实现见 `plugins/pickone/changes.py`。

## 4. 前端契约

`web/src/plugins/<slug>/index.js` 默认导出：

```js
export default {
  manifest,   // 必填：与后端同一份数据（含 nav / adminNav）
  routes,     // 必填：路由数组
  api,        // 可选：接口方法表
  async stat() { return { ok: true, label: '3 个条目' } },   // 可选：首页卡片
}
```

- **`stat()`** 框架只认三个字段，文案由插件自己拼（框架不认识「张图」这种属于具体工具的词汇）：
  `ok: false` 时卡片显示成告警、正文用 `hint`；否则显示 `label`。抛错/返回 null → 卡片退化成「进入工具」。
- **`routes`** 每条 `path` 都要以 `manifest.home` 开头 —— 导航栏靠这个前缀判断「当前在哪个工具里」。
- **`manifest.nav` / `adminNav`** 是导航项；`adminNav` 只对管理员显示。
- **不要 import `@/api`**（循环依赖，见 [`../AGENTS.md`](../AGENTS.md) 铁律 6），用 `./api`。
  视图里用 `@/api` 没问题。

### 接口方法表

```js
// web/src/plugins/mytool/api.js
import http from '@/api/http'
const BASE = '/plugins/mytool'

export default {
  listItems: () => http.get(`${BASE}/items`),
  // 框架的审核队列是通用的，插件包一层注入自己的 slug
  reviewQueue: (params) => http.get('/admin/queue', { params: { ...params, plugin: 'mytool' } }),
}
```

会被挂到 `api.mytool.*`。**视图里统一用 `api.mytool.方法名()`**：

- 平铺的 `api.方法名()` 是给早期代码留的兼容层，只有全站唯一的名字才会出现；
- 与框架接口重名时（例如 `reviewQueue`），平铺以**框架**为准；
- 两个插件之间重名时，两边都不平铺。

### 复用框架的通用审核台

路由直接指向框架组件，`meta.plugin` 由注册表自动写入：

```js
{ path: '/mytool/review', name: 'mytool-review',
  component: () => import('@/views/admin/PluginReviewView.vue'),
  meta: { title: '审核台', admin: true } }
```

需要领域专属的改动对比 / 冲突裁定界面时，再写自己的组件
（样板见 `web/src/plugins/pickone/views/ReviewView.vue`）。

## 5. 页面样式

全站样式类定义在 `web/src/styles/main.css`，直接复用，不要另起一套：
`ep-page` / `ep-page-head` / `ep-title` / `ep-subtitle` / `ep-actions` / `ep-stats` / `ep-stat` /
`ep-stat-label` / `ep-stat-value` / `ep-section` / `ep-card` / `ep-chip(--ok|--warn|--danger)` /
`ep-muted` / `ep-faint` / `ep-mb` / `ep-mono`。Element Plus 图标在 `main.js` 全局注册，
模板里直接写 `<Grid />`，不要 import。

## 6. 验证

```powershell
uv run python -m server.inspect check    # 只验契约（快）
uv run python -m server.inspect plugins  # 看接线：api 前缀、提交类型、前端 slug 是否对上
.\check.ps1                              # 全量：lint + 契约 + 测试 + 构建
```

`server.inspect check` 会报的几类问题：slug 不合法 / manifest 名称为空 / 路由为空 /
路由写死了 `/api` / 注册的提交类型与 manifest 不一致 / `health()` 不是 dict 或缺 `ok` /
前端 `manifest.js` 缺失或 slug 不一致。

## 7. 常见坑

- **前端契约变了，前端不一定立刻生效**：后端直接托管 `web/dist`，改完必须 `npm run build`
  （或 `.\start.ps1` 会自动判断是否需要重建）。
- **`plugins/` 下名字以 `_` 开头的目录会被跳过**。草稿、模板放那里最安全。
- **`CREATE TABLE IF NOT EXISTS` 不会改老表**。要给 `submissions` 加列/加索引，得写在
  `Repository._migrate_submissions_plugin()` 那种迁移函数里；把依赖新列的索引放进 `SCHEMA`
  会让老库在迁移前就报 `no such column`。
- **SQLite 的 `ALTER TABLE ... DEFAULT` 不接受占位符**，只能内联字面量（见
  `config.LEGACY_PLUGIN_SLUG` 的字符集校验）。
- **`app.routes` 看不到插件路由**：这个 FastAPI 版本用 `_IncludedRouter` 惰性包装
  `include_router`。要看路由表用 `server.inspect routes`（它走 `app.openapi()`）。
- **写盘要原子**：临时文件 + `os.replace`，别让并发请求读到半截 JSON。骨架和
  `plugins/pickone/store.py` 都是这么写的。
