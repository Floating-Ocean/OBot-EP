"""新插件脚手架：一条命令生成一个**能跑通**的工具骨架。

    uv run python -m server.scaffold mytool --name "My Tool" --tag "数据维护"

生成 `plugins/mytool/`（后端）与 `web/src/plugins/mytool/`（前端），立刻可被发现、
可访问、可通过契约检查 —— 所以写新工具的人只需要改领域逻辑，不用从零推导
「文件放哪、接口怎么写、怎么接到框架上」。

这是这个仓库最重要的省力装置：**契约由能跑的代码承载，而不是靠文档描述。**
模板本身就是真文件（`plugins/_template/`），所以它是可 lint、可阅读、可执行的说明书。
骨架里留下的 `TODO(<slug>)` 标记就是还需要改的地方，生成完会列出来。
"""

from __future__ import annotations

import argparse
import importlib
import re
import shutil
import sys
from pathlib import Path

from . import config

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")

TEMPLATE_DIR = config.PLUGINS_DIR / "_template"
BACKEND_TEMPLATE = TEMPLATE_DIR / "backend"
FRONTEND_TEMPLATE = TEMPLATE_DIR / "frontend"

# 模板里用不到的目录不要带进生成的插件
SKIP_NAMES = {"__pycache__"}


def _env_prefix(slug: str) -> str:
    return "OBOT_" + slug.upper().replace("-", "_")


def _class_name(slug: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_]", slug)) or "Tool"


def _substitute(text: str, slug: str, name: str, tag: str) -> str:
    for placeholder, value in (
        ("@@SLUG@@", slug),
        ("@@NAME@@", name),
        ("@@TAG@@", tag),
        ("@@CLASS@@", _class_name(slug)),
        ("@@ENV@@", _env_prefix(slug)),
    ):
        text = text.replace(placeholder, value)
    return text


def _copy_tree(source: Path, target: Path, slug: str, name: str, tag: str) -> list[Path]:
    written: list[Path] = []
    for path in sorted(source.rglob("*")):
        if any(part in SKIP_NAMES for part in path.parts):
            continue
        relative = path.relative_to(source)
        destination = target / relative
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            shutil.copy2(path, destination)
        else:
            destination.write_text(_substitute(text, slug, name, tag), encoding="utf-8")
        written.append(destination)
    return written


def scaffold(slug: str, name: str, tag: str, *, force: bool = False) -> list[Path]:
    """生成插件骨架，返回写入的文件列表。"""
    if not BACKEND_TEMPLATE.is_dir():
        raise FileNotFoundError(f"plugin template missing: {BACKEND_TEMPLATE}")

    backend_root = config.PLUGINS_DIR / slug
    frontend_root = config.BASE_DIR / "web" / "src" / "plugins" / slug

    for root in (backend_root, frontend_root):
        if root.exists():
            if not force:
                raise FileExistsError(f"{root} already exists (use --force to overwrite)")
            shutil.rmtree(root)

    written = _copy_tree(BACKEND_TEMPLATE, backend_root, slug, name, tag)
    written += _copy_tree(FRONTEND_TEMPLATE, frontend_root, slug, name, tag)
    return written


def _validate(slug: str) -> list[str]:
    """生成后立刻按插件契约自检 —— 模板坏掉要当场知道，而不是等用的人踩坑。"""
    from .inspect import check_plugin

    module = importlib.import_module(f"{config.PLUGINS_DIR.name}.{slug}")
    return check_plugin(module.PLUGIN)


def _todo_markers(slug: str) -> list[str]:
    marker = f"TODO({slug})"
    found: list[str] = []
    for root in (config.PLUGINS_DIR / slug, config.BASE_DIR / "web" / "src" / "plugins" / slug):
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if marker in line:
                    found.append(f"{path.relative_to(config.BASE_DIR)}:{number}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="server.scaffold", description="generate a new OBot-EP plugin skeleton"
    )
    parser.add_argument("slug", help="plugin id, e.g. mytool (lowercase, dashes ok)")
    parser.add_argument("--name", default="", help="display name (default: the slug)")
    parser.add_argument("--tag", default="", help="short chip on the hub card")
    parser.add_argument("--force", action="store_true", help="overwrite an existing plugin")
    args = parser.parse_args(argv)

    slug = args.slug.strip()
    if not SLUG_RE.fullmatch(slug):
        print(f"[x] invalid slug {slug!r}: use [a-z0-9][a-z0-9_-]*")
        return 1
    if slug.startswith("_"):
        print("[x] a slug must not start with '_' (those directories are skipped by discovery)")
        return 1

    name = args.name.strip() or slug
    tag = args.tag.strip() or "数据维护"

    try:
        written = scaffold(slug, name, tag, force=args.force)
    except (FileExistsError, FileNotFoundError) as error:
        print(f"[x] {error}")
        return 1

    print(f"[ok] wrote {len(written)} file(s) for plugin '{slug}'")
    print(f"     backend : plugins/{slug}/")
    print(f"     frontend: web/src/plugins/{slug}/")

    problems = _validate(slug)
    errors = [item for item in problems if item.startswith("ERROR")]
    if errors:
        print("\n[x] the generated plugin FAILED the plugin contract:")
        for item in problems:
            print(f"    {item}")
        print("    (this means plugins/_template/ is broken, not your input)")
        return 1
    print("\n[ok] generated plugin passes the plugin contract")

    todos = _todo_markers(slug)
    print(f"\nWhat is left ({len(todos)} TODO marker(s)):")
    for item in todos:
        print(f"  {item}")
    print(
        "\nNext:\n"
        f"  1. plugins/{slug}/store.py                    read/write the real data\n"
        f"  2. plugins/{slug}/types.py + schemas.py       which fields can change\n"
        f"  3. plugins/{slug}/api/items.py + api/admin.py routes and write-back\n"
        f"  4. plugins/{slug}/plugin.py                   name, icon, accent, health\n"
        f"  5. web/src/plugins/{slug}/views/ItemsView.vue the page\n"
        "  6. .\\check.ps1"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
