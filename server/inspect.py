"""自省 CLI：把「这个项目里有什么」直接打印出来。

存在的意义是**省掉探路成本**：想知道有哪些插件、某个插件的接口挂在哪、路由表长什么样，
跑一条命令就行，不用写临时脚本、不用去猜路由是怎么装配的。

    uv run python -m server.inspect plugins                    # 插件清单 + 磁盘/前端是否对齐
    uv run python -m server.inspect routes                     # 全部路由，按框架/插件分组
    uv run python -m server.inspect routes --plugin pickone    # 只看某个插件

输出一律 ASCII 英文 —— 折叠成表格给终端看的，不该依赖 CJK 字体。
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
from pathlib import Path

from . import config
from .plugin import PluginRegistry, discover_plugins
from .repository import known_submission_types

# 插件 slug 的合法字符集，与 config.LEGACY_PLUGIN_SLUG 的校验保持一致
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _registry() -> PluginRegistry:
    return PluginRegistry(discover_plugins())


def _frontend_dir(slug: str) -> Path:
    return config.BASE_DIR / "web" / "src" / "plugins" / slug


def _frontend_slug_matches(slug: str) -> bool | None:
    """前端 manifest.js 里的 slug 是否与后端一致。

    这是唯一一处跨语言、靠约定对齐的地方，错了只会在浏览器里表现为「工具不在首页上」，
    所以这里主动查一下。返回 None 表示前端插件还没建。
    """
    manifest = _frontend_dir(slug) / "manifest.js"
    if not manifest.is_file():
        return None
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return None
    found = re.search(r"slug:\s*['\"]([^'\"]+)['\"]", text)
    return bool(found and found.group(1) == slug)


def check_plugin(plugin) -> list[str]:
    """校验一个插件是否符合契约，返回问题列表（空 = 合规）。

    这是**可执行的文档**：插件契约写在 AGENTS.md 里，而这里把它变成能跑的检查。
    脚手架生成完新插件会立刻调它，CI 用 `python -m server.inspect check` 调它，
    所以「照着抄但抄漏了一步」会当场被指出来，而不是等到运行时才炸。

    每条问题以 `ERROR:` 或 `WARN:` 开头。
    """
    problems: list[str] = []
    slug = plugin.slug
    manifest = plugin.manifest

    if not SLUG_RE.fullmatch(slug):
        problems.append(f"ERROR: slug {slug!r} must match [a-z0-9][a-z0-9_-]*")
    if not manifest.name.strip():
        problems.append("ERROR: manifest.name is empty (the hub needs a display name)")
    if manifest.home and not manifest.home.startswith("/"):
        problems.append(f"ERROR: manifest.home {manifest.home!r} must start with '/'")

    routes = list(plugin.router.routes)
    if not routes:
        problems.append("ERROR: build_router() returned a router with no routes")
    for route in routes:
        path = getattr(route, "path", "")
        if path.startswith("/api"):
            # 路由会被挂到 api_prefix 下，写死 /api 会变成 /api/plugins/<slug>/api/...
            problems.append(f"ERROR: route {path!r} must be relative to the plugin prefix")

    declared = set(manifest.submission_types)
    registered = set(known_submission_types(slug))
    if declared != registered:
        problems.append(
            "ERROR: manifest.submission_types and register_submission_types() disagree"
            f" (manifest={sorted(declared)}, registered={sorted(registered)})"
        )

    try:
        health = plugin.health()
        if not isinstance(health, dict):
            problems.append(f"ERROR: health() returned {type(health).__name__}, expected dict")
        elif "ok" not in health:
            problems.append("ERROR: health() must include an 'ok' key")
    except Exception as error:  # noqa: BLE001 - 自省工具要如实报告，而不是自己崩掉
        problems.append(f"ERROR: health() raised {type(error).__name__}: {error}")

    try:
        versions = plugin.versions()
        if not isinstance(versions, dict):
            problems.append(f"ERROR: versions() returned {type(versions).__name__}, expected dict")
        else:
            bad = [key for key, value in versions.items() if value is not None and not isinstance(value, str)]
            if bad:
                problems.append(f"ERROR: versions() values must be str or None: {bad}")
    except Exception as error:  # noqa: BLE001
        problems.append(f"ERROR: versions() raised {type(error).__name__}: {error}")

    matched = _frontend_slug_matches(slug)
    if matched is None:
        problems.append(
            f"WARN: web/src/plugins/{slug}/manifest.js not found "
            "(the tool will not appear in the frontend hub)"
        )
    elif matched is False:
        problems.append(
            f"ERROR: web/src/plugins/{slug}/manifest.js declares a different slug"
        )

    return problems


def cmd_check(args: argparse.Namespace) -> int:
    registry = _registry()
    if not len(registry):
        print("ERROR: no plugins loaded from plugins/")
        return 1

    failed = 0
    for plugin in registry:
        problems = check_plugin(plugin)
        errors = [item for item in problems if item.startswith("ERROR")]
        if problems:
            print(f"[{plugin.slug}]")
            for item in problems:
                print(f"  {item}")
        else:
            print(f"[{plugin.slug}] ok")
        failed += len(errors)

    print(f"\n{len(registry)} plugin(s) checked, {failed} error(s)")
    return 1 if failed else 0


def cmd_plugins(args: argparse.Namespace) -> int:
    # 用模块级 app 拿真实路由数：APIRouter.include_router 在这个 FastAPI 版本里也是
    # 惰性的，直接数 plugin.router.routes 只会得到「子路由个数」，不是接口个数。
    from .app import app

    registry = app.state.plugins
    if not len(registry):
        print("No plugins loaded. Each tool is a package under plugins/<slug>/ exporting PLUGIN.")
        return 1

    per_plugin: dict[str, int] = {plugin.slug: 0 for plugin in registry}
    for _method, path in _all_routes(app):
        for slug, prefix in ((p.slug, p.api_prefix) for p in registry):
            if path == prefix or path.startswith(prefix + "/"):
                per_plugin[slug] += 1
                break

    print(f"{'SLUG':<14} {'HOME':<14} {'ROUTES':>6} {'HEALTH':<10} {'FRONTEND':<13} NAME")
    for plugin in registry:
        try:
            health = plugin.health()
            health_text = "ok" if health.get("ok", True) else "NOT READY"
        except Exception as error:  # noqa: BLE001 - 自省工具不该因为插件坏了就崩
            health_text = f"error({type(error).__name__})"

        matched = _frontend_slug_matches(plugin.slug)
        frontend = {None: "missing", True: "ok", False: "SLUG MISMATCH"}[matched]

        print(
            f"{plugin.slug:<14} {plugin.manifest.home or '-':<14} {per_plugin[plugin.slug]:>6} "
            f"{health_text:<10} {frontend:<13} {plugin.manifest.name}"
        )

        types = known_submission_types(plugin.slug)
        print(f"{'':<14} api={plugin.api_prefix}")
        print(f"{'':<14} submission_types={', '.join(types) if types else '-'}")
        if health.get("ok") is False:
            print(f"{'':<14} health={health}")

    return 0


def _all_routes(app) -> list[tuple[str, str]]:
    """(method, path) 列表。

    刻意走 `app.openapi()` 而不是遍历 `app.routes`：这个 FastAPI 版本用
    `_IncludedRouter` 惰性包装 include_router，`app.routes` 里看不到展开后的路径。
    """
    spec = app.openapi()
    pairs: list[tuple[str, str]] = []
    for path, operations in spec.get("paths", {}).items():
        for method in operations:
            pairs.append((method.upper(), path))
    return sorted(pairs, key=lambda item: (item[1], item[0]))


def cmd_routes(args: argparse.Namespace) -> int:
    # 用模块级的 app：它已经由 create_app() 建好并注册了所有路由。
    # 再调一次 create_app() 会把插件重新发现一遍（日志里就会出现两遍 loaded）。
    from .app import app

    registry = app.state.plugins
    pairs = _all_routes(app)

    plugin_prefix = {plugin.slug: plugin.api_prefix for plugin in registry}
    buckets: dict[str, list[tuple[str, str]]] = {"(framework)": []}
    for slug in plugin_prefix:
        buckets[f"plugin:{slug}"] = []

    for method, path in pairs:
        owner = "(framework)"
        for slug, prefix in plugin_prefix.items():
            if path == prefix or path.startswith(prefix + "/"):
                owner = f"plugin:{slug}"
                break
        buckets[owner].append((method, path))

    for owner, entries in buckets.items():
        if args.plugin and owner not in (f"plugin:{args.plugin}",):
            continue
        if not entries:
            continue
        if owner.startswith("plugin:"):
            slug = owner.split(":", 1)[1]
            print(f"\n{owner}   ->  {plugin_prefix[slug]}")
        else:
            print(f"\n{owner}")
        for method, path in entries:
            print(f"  {method:<7} {path}")

    print(f"\ntotal: {len(pairs)} route(s), {len(registry)} plugin(s)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="server.inspect", description="OBot-EP introspection (plugins / routes)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plugins", help="list loaded plugins and their wiring").set_defaults(
        func=cmd_plugins
    )
    routes = sub.add_parser("routes", help="list every HTTP route by owner")
    routes.add_argument("--plugin", default="", help="only show this plugin's routes")
    routes.set_defaults(func=cmd_routes)

    sub.add_parser("check", help="validate every plugin against the plugin contract").set_defaults(
        func=cmd_check
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # 插件显示名是中文，而 Windows 控制台默认可能是 GBK：不改的话表格里是乱码
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, ValueError):  # pragma: no cover
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
