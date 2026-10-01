# 新插件模板

**这个目录不是插件。** 名字以 `_` 开头，`server.plugin.discover_plugins()` 和前端
`web/src/plugins/registry.js` 都会跳过它。

```
plugins/_template/backend/    后端模板 → 拷贝到 plugins/<slug>/
plugins/_template/frontend/   前端模板 → 拷贝到 web/src/plugins/<slug>/
```

模板里用 `@@SLUG@@` / `@@NAME@@` / `@@TAG@@` / `@@CLASS@@` / `@@ENV@@` 占位，
由 `server/scaffold.py` 替换。

## 怎么用

```powershell
uv run python -m server.scaffold mytool --name "My Tool" --tag "数据维护"
```

生成完会**自动跑一遍插件契约检查**（`python -m server.inspect check`）并列出
剩下的 `TODO(mytool)` —— 那份清单就是还需要改的地方。

## 为什么模板是真文件而不是代码里的字符串

模板就是「怎么写出一个插件」的说明书，而且它是**能跑的**：

- 真文件可以被 `ruff` 检查、可以被编辑器高亮、可以直接阅读；
- 不用在字符串里转义 `{` `}`（Vue 的 `{{ }}`、Python 的 f-string 在字符串模板里
  是灾难）；
- 改模板的代价很低，改完立刻验证：

```powershell
uv run python tests/scaffold_test.py     # 生成 → 契约校验 → 清理
```
