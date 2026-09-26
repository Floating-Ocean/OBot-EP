"""Read-only cross-check script: compares OBot-EP parsing/encoding results against OBot-ACM real data.

Performs no writes. Run:
  .venv\\Scripts\\python.exe tests\\verify_real_data.py
"""

from __future__ import annotations

import ast
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ACM = ROOT.parent / "OBot-ACM"
LIB = ACM / "lib" / "Pick-One"
BOT_TOOLS = ACM / "src" / "core" / "util" / "tools.py"

os.environ.setdefault("OBOT_PICK_ONE_DIR", str(LIB))

from server import hashing  # noqa: E402
from server.store import PickOneStore  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  [PASS] {label}")
    else:
        FAILED.append(label)
        print(f"  [FAIL] {label} {extra}")


def load_bot_functions() -> dict:
    """Extract function definitions from the Bot's tools.py by name and execute them, for cross-checking.

    Only these pure functions are executed, to avoid importing the whole module
    (which would pull in the Bot's heavy dependencies).
    """
    source = BOT_TOOLS.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"md5_to_base62", "base62_to_md5"}
    picked = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if len(picked) != len(wanted):
        raise RuntimeError(f"did not find all target functions in {BOT_TOOLS}: {[n.name for n in picked]}")

    module = ast.Module(body=picked, type_ignores=[])
    # These functions only use string.ascii_letters and format(), so adding that dependency is enough
    import string

    namespace: dict = {"string": string}
    exec(compile(module, str(BOT_TOOLS), "exec"), namespace)  # noqa: S102
    return namespace


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if not LIB.is_dir():
        print(f"Pick-One data directory not found: {LIB}")
        return 2

    print("== Base62 encoding consistent with the Bot implementation ==")
    bot = load_bot_functions()
    samples = [
        "0029cf9d2dd8c981a0e741e43ab8719d",
        "ffffffffffffffffffffffffffffffff",
        "00000000000000000000000000000001",
        "d41d8cd98f00b204e9800998ecf8427e",
    ]
    for md5 in samples:
        mine = hashing.md5_to_base62(md5)
        theirs = bot["md5_to_base62"](md5)
        check(f"md5_to_base62({md5[:8]}...) match", mine == theirs, f"{mine} != {theirs}")
        back = hashing.base62_to_md5(mine)
        check(f"base62_to_md5 round trip ({md5[:8]}...)", back == md5.lower(), back)

    print("\n== Real data parsing ==")
    store = PickOneStore(LIB)
    categories = store.list_categories()
    check("category count > 0", len(categories) > 0, str(len(categories)))

    total_parser_keys = 0
    total_images = 0
    legacy = 0
    missing_ocr = 0
    extra_field_cases = 0
    mismatched = []

    for category in categories:
        parser = store.load_raw_parser(category.img_key)
        raw_keys = {key for key in parser if key.endswith(".gif")}
        files = set(store.list_images(category.img_key))
        total_parser_keys += len(raw_keys)
        total_images += len(files)

        if raw_keys != files:
            mismatched.append(
                f"{category.img_key}: parser={len(raw_keys)} files={len(files)}"
            )

        for stat in store.iter_image_stats(category.img_key):
            if stat.legacy:
                legacy += 1
            if stat.needs_ocr:
                missing_ocr += 1
            if stat.extra:
                extra_field_cases += 1

    print(f"  {total_images} images, {total_parser_keys} parser entries")
    print(f"  {legacy} legacy string entries, {missing_ocr} images missing OCR")
    check("image and parser entry counts match", total_images == total_parser_keys, f"{total_images} != {total_parser_keys}")
    check("no category has an image/parser mismatch", not mismatched, "; ".join(mismatched[:5]))
    check("legacy string entries detected", legacy > 0, str(legacy))
    print(f"  entries with extra fields (kept as-is): {extra_field_cases}")

    print("\n== Lossless normalization (stats reading layer) ==")
    # The stats layer is read-only and must not modify any file
    before_mtimes = {
        path: path.stat().st_mtime_ns
        for path in LIB.rglob("parser.json")
    }
    for category in categories:
        list(store.iter_image_stats(category.img_key))
    after_mtimes = {path: path.stat().st_mtime_ns for path in LIB.rglob("parser.json")}
    check("reading stats does not modify parser.json", before_mtimes == after_mtimes)

    print("\n== Write-back compatibility (verified on a temporary copy, real data untouched) ==")
    import shutil
    import tempfile

    tmp_dir = ROOT / ".tmp" / "roundtrip"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    try:
        # Copy only one small category to verify "the Bot can still read it back in the original structure after a write"
        source_key = min(
            (item.img_key for item in categories if item.image_count > 0),
            key=lambda key: next(item.image_count for item in categories if item.img_key == key),
        )
        shutil.copytree(LIB / source_key, tmp_dir / source_key)
        shutil.copy2(LIB / "config.json", tmp_dir / "config.json")

        tmp_store = PickOneStore(tmp_dir)
        parser = tmp_store.load_raw_parser(source_key)
        names = tmp_store.list_images(source_key)
        check(f"sample category selected {source_key}", bool(names), str(names[:3]))

        target = names[0]
        original_entry = parser[target]
        is_legacy = isinstance(original_entry, str)
        before_likes = 0 if is_legacy else int(original_entry.get("likes") or 0)

        # Simulate one real write-back: change ocr_text + add likes + comments
        tmp_store.apply_image_changes(
            {
                source_key: [
                    {"name": target, "field": "ocr_text", "value": "往返测试文本"},
                    {"name": target, "field": "likes", "value": 7},
                    {"name": target, "field": "comments", "value": ["第一条", "第二条"]},
                ]
            }
        )

        written = tmp_store.load_raw_parser(source_key)
        entry = written[target]
        check("still a dict structure after writing", isinstance(entry, dict), str(type(entry)))
        check("ocr_text written", entry["ocr_text"] == "往返测试文本", str(entry))
        check(
            "likes added on top of the original value",
            entry["likes"] == before_likes + 7,
            f"{before_likes} + 7 != {entry['likes']}",
        )
        check("comments written", entry["comments"] == ["第一条", "第二条"])
        check(
            "all five standard fields present",
            set(entry) >= {"ocr_text", "add_time", "likes", "comments", "pickup_times"},
            str(sorted(entry)),
        )
        if is_legacy:
            check("legacy string entry has add_time after upgrade", float(entry["add_time"]) > 0)

        # The JSON on disk must be directly readable by the Bot's json.load
        raw_text = (tmp_dir / source_key / "parser.json").read_text(encoding="utf-8")
        reloaded = json.loads(raw_text)
        check("Bot's json.load can parse it directly", isinstance(reloaded, dict) and target in reloaded)

        # The Bot-side stats logic (get_category_stat/_build_img_stat) relies on these keys
        stat_entry = reloaded[target]
        check(
            "field types required by the Bot are correct",
            isinstance(stat_entry["ocr_text"], str)
            and isinstance(stat_entry["likes"], int)
            and isinstance(stat_entry["comments"], list)
            and isinstance(stat_entry["pickup_times"], int),
            str({k: type(v).__name__ for k, v in stat_entry.items()}),
        )

        # Category write
        tmp_store.apply_category_entries(
            {source_key: {"id": "往返测试", "key": ["往返测试", "roundtrip"]}}
        )
        config = read_json(tmp_dir / "config.json")
        check("config.json category written successfully", config[source_key]["id"] == "往返测试", str(config.get(source_key)))

        # Other entries must not be affected
        untouched = [name for name in names if name != target]
        if untouched:
            other = untouched[0]
            check(
                "other entries stay unchanged",
                reloaded[other] == parser[other],
                f"{other} was modified",
            )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print(f"\n{'=' * 60}\npassed {len(PASSED)}, failed {len(FAILED)}")
    if FAILED:
        for item in FAILED:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
