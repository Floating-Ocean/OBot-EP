"""脚手架自检：生成一个临时插件 → 校验契约 → 清理。

存在的意义是**防止模板腐烂**。`plugins/_template/` 是「怎么写出一个插件」的说明书，
但说明书会过期：改了框架的插件契约却忘了改模板，要等到下次有人真的建工具时才会炸。
这里每次跑一遍生成流程，把这个问题提前到测试里。

用法：

    uv run python tests/scaffold_test.py
"""

from __future__ import annotations

import contextlib
import importlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 临时插件的 slug。必须是个**合法** slug —— 契约检查会校验字符集，
# 用 _ 开头虽然能让发现逻辑跳过它，但也就绕过了「生成物必须合规」这件事本身。
# 残留风险由「进入时先 rmtree + finally 里 rmtree」兜住：真被打断也只是让
# 首页多出一个叫 Scaffold Test 的工具，下次跑这个脚本就会清掉。
SLUG = "scaffoldtmp"

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  [PASS] {label}")
    else:
        FAILED.append(label)
        print(f"  [FAIL] {label} {extra}")


def main() -> int:
    print("== Scaffold round trip ==")

    from server import config
    from server.inspect import check_plugin
    from server.scaffold import scaffold

    backend = config.PLUGINS_DIR / SLUG
    frontend = config.BASE_DIR / "web" / "src" / "plugins" / SLUG

    # 上一次跑崩了也别把残留带进来
    for path in (backend, frontend):
        shutil.rmtree(path, ignore_errors=True)

    try:
        written = scaffold(SLUG, "Scaffold Test", "test", force=True)
        check("Scaffold writes files", len(written) >= 10, f"wrote {len(written)}")

        expected_backend = [
            "__init__.py",
            "config.py",
            "plugin.py",
            "schemas.py",
            "store.py",
            "types.py",
            "api/__init__.py",
            "api/admin.py",
            "api/deps.py",
            "api/items.py",
        ]
        missing = [name for name in expected_backend if not (backend / name).is_file()]
        check("Backend skeleton is complete", not missing, f"missing {missing}")

        expected_frontend = [
            "index.js",
            "manifest.js",
            "routes.js",
            "api.js",
            "views/ItemsView.vue",
        ]
        missing = [name for name in expected_frontend if not (frontend / name).is_file()]
        check("Frontend skeleton is complete", not missing, f"missing {missing}")

        # 模板里不应该残留没被替换掉的占位符
        leftovers: list[str] = []
        for path in list(backend.rglob("*")) + list(frontend.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if "@@" in text:
                leftovers.append(str(path.relative_to(ROOT)))
        check("No unreplaced @@PLACEHOLDER@@ left", not leftovers, f"{leftovers[:5]}")

        # 生成的插件必须立刻通过契约检查（这是脚手架自己也会做的事）
        module = importlib.import_module(f"plugins.{SLUG}")
        problems = check_plugin(module.PLUGIN)
        check("Generated plugin passes the contract", not problems, "; ".join(problems))

        # 生成的 Python 必须能被解释器接受（语法的最后一道闸）
        import py_compile

        broken: list[str] = []
        for path in backend.rglob("*.py"):
            try:
                py_compile.compile(str(path), doraise=True, cfile=None)
            except py_compile.PyCompileError as error:
                broken.append(f"{path.name}: {error.msg}")
        check("Generated Python compiles", not broken, "; ".join(broken))

        # slug 校验：非法 slug 必须被拒绝，否则会生成一个永远加载不了的包
        from server.scaffold import SLUG_RE

        check("Rejects an invalid slug", not SLUG_RE.fullmatch("Bad Slug"))
        check("Accepts a dashed slug", bool(SLUG_RE.fullmatch("my-tool2")))
    finally:
        # 一定要清掉：留着的话 server.inspect check 会去 import 这个临时插件
        for path in (backend, frontend):
            shutil.rmtree(path, ignore_errors=True)
        with contextlib.suppress(KeyError):
            sys.modules.pop(f"plugins.{SLUG}", None)

    print(f"\n{'=' * 60}\npassed {len(PASSED)}, failed {len(FAILED)}")
    if FAILED:
        print("Failed:")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
