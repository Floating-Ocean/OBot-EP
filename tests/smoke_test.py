"""End-to-end smoke test.

To avoid depending on write permissions outside the sandbox and to leave real
data untouched, this generates a Pick-One directory structure on the fly
(config.json / parser.json / *.gif) as a fixture, then points
`OBOT_PICK_ONE_DIR` at it to run the full "submit -> review -> one-click apply"
flow.

Run: .venv\\Scripts\\python.exe tests\\smoke_test.py
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP_ROOT = ROOT / ".tmp"
FIXTURE = TMP_ROOT / "pick-one-fixture"
DATA_DIR = TMP_ROOT / "smoke-data"

os.environ["OBOT_PICK_ONE_DIR"] = str(FIXTURE)
os.environ["OBOT_EP_DATA_DIR"] = str(DATA_DIR)
os.environ["OBOT_EP_ADMIN_PASSWORD"] = "admin12345"
os.environ["OBOT_EP_SECRET"] = "smoke-test-secret"

from PIL import Image  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.app import app  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []

NEW_CATEGORY = "smoke_test_cat"

# Fixed MD5 values (32 hex chars), matching the Bot's naming rule
MD5S = [
    "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
    "1a2b3c4d5e6f70819273a4b5c6d7e8f9",
    "2b3c4d5e6f708192a3b4c5d6e7f80910",
    "3c4d5e6f708192a3b4c5d6e7f8091a2b",
    "4d5e6f708192a3b4c5d6e7f8091a2b3c",
    "5e6f708192a3b4c5d6e7f8091a2b3c4d",
    "6f708192a3b4c5d6e7f8091a2b3c4d5e",
    "708192a3b4c5d6e7f8091a2b3c4d5e6f",
]


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  [PASS] {label}")
    else:
        FAILED.append(label)
        print(f"  [FAIL] {label} {extra}")


def make_gif(color: tuple[int, int, int], frames: int = 3) -> bytes:
    images = [Image.new("RGB", (40, 40), color) for _ in range(frames)]
    buffer = io.BytesIO()
    images[0].save(
        buffer, format="GIF", save_all=True, append_images=images[1:], duration=120, loop=0
    )
    return buffer.getvalue()


def build_fixture() -> None:
    """Build a minimal usable Pick-One data directory."""
    shutil.rmtree(FIXTURE, ignore_errors=True)
    shutil.rmtree(DATA_DIR, ignore_errors=True)

    (FIXTURE / "lzh").mkdir(parents=True)
    (FIXTURE / "kepy").mkdir(parents=True)
    (FIXTURE / "__AUDIT__").mkdir(parents=True)

    for index, md5 in enumerate(MD5S):
        (FIXTURE / "lzh" / f"{md5}.gif").write_bytes(make_gif((30 + index * 20, 90, 160)))

    # lzh: half dict-structured, half legacy string entries (mirrors 964 legacy records)
    lzh_parser: dict = {}
    for index, md5 in enumerate(MD5S):
        if index < 4:
            lzh_parser[f"{md5}.gif"] = {
                "ocr_text": f"旧文本{index}",
                "add_time": 1700000000.0 + index,
                "likes": index,
                "comments": [f"评论{index}"] if index == 1 else [],
                "pickup_times": index * 2,
            }
        else:
            lzh_parser[f"{md5}.gif"] = f"遗留字符串文本{index}"

    (FIXTURE / "lzh" / "parser.json").write_text(
        json.dumps(lzh_parser, ensure_ascii=False, indent=4), encoding="utf-8"
    )

    # kepy: has images but no entries in parser.json (this really happens in production)
    (FIXTURE / "kepy" / f"{MD5S[0]}.gif").write_bytes(make_gif((200, 80, 40)))
    (FIXTURE / "kepy" / "parser.json").write_text("{}", encoding="utf-8")

    # Empty category (present in config, but no images in its directory)
    (FIXTURE / "empty_cat").mkdir()

    config = {
        "lzh": {"id": "小廖", "key": ["小廖", "xl", "lzh"]},
        "kepy": {"id": "Kepy", "key": ["杰尼龟", "龟", "kepy"]},
        "empty_cat": {"id": "空类别", "key": ["空类别", "empty_cat"]},
    }
    (FIXTURE / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def main() -> int:
    build_fixture()
    config_path = FIXTURE / "config.json"
    parser_path = FIXTURE / "lzh" / "parser.json"
    config_before = config_path.read_text(encoding="utf-8")
    parser_before = parser_path.read_text(encoding="utf-8")

    try:
        admin_client = TestClient(app)
        alice = TestClient(app)
        bob = TestClient(app)
        with admin_client, alice, bob:
            print("\n== Auth ==")
            r = admin_client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin12345"}
            )
            check("Admin login", r.status_code == 200 and r.json()["user"]["is_admin"], r.text[:200])

            r = alice.post(
                "/api/auth/register",
                json={"username": "alice", "password": "alice12345", "display_name": "Alice"},
            )
            check(
                "Regular user registers and is logged in automatically",
                r.status_code == 201,
                r.text[:200],
            )

            r = alice.post("/api/auth/login", json={"username": "alice", "password": "alice12345"})
            check("Regular user login", r.status_code == 200)
            r = alice.get("/api/admin/queue")
            check(
                "Regular user denied on admin endpoint",
                r.status_code == 403,
                str(r.status_code),
            )
            r = alice.post("/api/auth/login", json={"username": "alice", "password": "wrong"})
            check("Wrong password rejected", r.status_code == 401)

            print("\n== Browsing ==")
            r = alice.get("/api/categories")
            body = r.json()
            check("Category list", r.status_code == 200 and len(body["categories"]) == 3, r.text[:200])
            lzh = next(item for item in body["categories"] if item["img_key"] == "lzh")
            check("Image count stats", lzh["image_count"] == 8, str(lzh["image_count"]))

            r = alice.get("/api/categories/summary")
            check(
                "Missing OCR stats (kepy has 1 image without parser)",
                r.json()["missing_ocr"] == 1,
                json.dumps(r.json(), ensure_ascii=False),
            )

            r = alice.get("/api/images/lzh", params={"page_size": 100})
            items = r.json()["items"]
            check("Image list", r.status_code == 200 and len(items) == 8, r.text[:200])
            check("Legacy string entries detected", any(item["legacy"] for item in items))
            check("Display ID is Base62", all(item["hash_id"] for item in items))

            missing = alice.get("/api/images/kepy").json()["items"]
            check(
                "Images missing from parser shown with empty text",
                missing[0]["ocr_text"] == "" and missing[0]["legacy"],
            )

            target = items[0]
            name = target["name"]
            original_text = target["ocr_text"]

            r = alice.get(f"/api/images/lzh/thumb/{name}")
            check("Thumbnail",
                r.status_code == 200 and r.headers["content-type"] == "image/webp",
                r.text[:120],
            )
            r = alice.get(f"/api/images/lzh/raw/{name}")
            check("Original image", r.status_code == 200 and r.content[:3] == b"GIF", str(r.status_code))

            r = alice.get("/api/images/lzh/raw/..%2F..%2Fconfig.json")
            check("Path traversal blocked", r.status_code in (400, 404), str(r.status_code))

            r = alice.get(f"/api/images/lzh/hash-id/{target['hash_id']}")
            check(
                "Reverse lookup by Base62 ID", r.status_code == 200 and r.json()["name"] == name, r.text[:200]
            )

            r = alice.get("/api/images/lzh", params={"q": original_text, "page_size": 100})
            check("Search by text", r.json()["total"] >= 1, str(r.json()["total"]))

            print("\n== OCR text correction ==")
            new_text = "冒烟测试文本-SMOKE"
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": new_text, "note": "改个错别字"},
            )
            check("Submit OCR change", r.status_code == 201, r.text[:300])
            submission_id = r.json()["submission"]["id"]

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": original_text},
            )
            check("Submit identical to current value rejected", r.status_code == 400, r.text[:200])

            r = alice.get("/api/images/lzh", params={"filter": "has_change", "page_size": 100})
            changed = r.json()["items"]
            check(
                "Pending changes are listed next to the original value",
                len(changed) == 1
                and changed[0]["ocr_text"] == original_text
                and changed[0]["has_pending_change"]
                and changed[0]["pending_fields"] == ["ocr_text"]
                and changed[0]["pending_changes"][0]["value"] == new_text
                and changed[0]["pending_changes"][0]["mine"] is True,
                json.dumps(changed[:1], ensure_ascii=False),
            )

            check("Disk untouched before review", "SMOKE" not in parser_path.read_text(encoding="utf-8"))

            r = alice.get("/api/submissions", params={"status": "open"})
            check("My submissions list", r.json()["total"] == 1, r.text[:200])
            check(
                "Per-user counts are separate from global counts",
                r.json()["mine"]["pending"] == 1 and r.json()["counts"]["pending"] == 1,
                json.dumps({"mine": r.json()["mine"], "counts": r.json()["counts"]}),
            )

            # 管理员给同一张图提修改：两个人应该各占一条，互相不挡
            # 而且别人的在途改动只能看，不能当成自己的修改起点
            admin_view = admin_client.get(
                "/api/images/lzh", params={"page_size": 100, "q": name.replace(".gif", "")}
            ).json()["items"][0]
            check(
                "Other users still see the original value",
                admin_view["ocr_text"] == original_text
                and admin_view["pending_changes"][0]["value"] == new_text
                and admin_view["pending_changes"][0]["mine"] is False,
                json.dumps(admin_view, ensure_ascii=False),
            )

            r = admin_client.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": "admin-own-text"},
            )
            check("Second user can edit the same image", r.status_code == 201, r.text[:250])
            admin_submission_id = r.json()["submission"]["id"]
            check(
                "A second editor submits against the original value",
                r.json()["submission"]["base_value"] == original_text
                and r.json()["submission"]["submitted_value"] == "admin-own-text",
                json.dumps(r.json()["submission"], ensure_ascii=False),
            )
            check(
                "Rows are per-author, not per-target",
                admin_submission_id != submission_id,
                f"{admin_submission_id} vs {submission_id}",
            )

            r = admin_client.get("/api/submissions", params={"scope": "mine", "status": "open"})
            check(
                "Admin sees own count, while global counts both",
                r.json()["total"] == 1 and r.json()["counts"]["pending"] == 2,
                json.dumps({"total": r.json()["total"], "counts": r.json()["counts"]}),
            )
            check(
                "Admin can list everyone's submissions",
                admin_client.get(
                    "/api/submissions", params={"scope": "all", "status": "open"}
                ).json()["total"]
                == 2,
            )
            admin_client.delete(f"/api/submissions/{admin_submission_id}")

            print("\n== Review ==")
            r = admin_client.get("/api/admin/queue", params={"status": "pending"})
            check("Pending review queue", r.status_code == 200 and r.json()["total"] == 1, r.text[:200])

            r = admin_client.post(
                f"/api/admin/review/{submission_id}", json={"approve": False, "comment": "测试驳回"}
            )
            check(
                "Reject",
                r.status_code == 200 and r.json()["submission"]["status"] == "rejected",
                r.text[:200],
            )

            r = admin_client.post(f"/api/admin/review/{submission_id}", json={"approve": True})
            check("Reviewed submission cannot be reviewed again", r.status_code == 409, str(r.status_code))

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": new_text, "note": "再来一次"},
            )
            submission_id = r.json()["submission"]["id"]
            r = admin_client.post(
                f"/api/admin/review/{submission_id}", json={"approve": True, "comment": "通过"}
            )
            check("Approve", r.status_code == 200 and r.json()["submission"]["status"] == "approved")
            check("Still not written to disk after approval", "SMOKE" not in parser_path.read_text(encoding="utf-8"))

            print("\n== Revoke the approval ==")
            r = alice.post(f"/api/admin/unreview/{submission_id}")
            check("Regular user cannot revoke an approval", r.status_code == 403, str(r.status_code))

            r = admin_client.post(f"/api/admin/unreview/{submission_id}")
            check(
                "An approved submission can be sent back to pending",
                r.status_code == 200
                and r.json()["submission"]["status"] == "pending"
                and r.json()["submission"]["review_comment"] == "",
                r.text[:200],
            )
            check(
                "The approved count drops back",
                admin_client.get("/api/admin/queue", params={"status": "approved"}).json()["total"] == 0,
            )
            r = admin_client.post(f"/api/admin/unreview/{submission_id}")
            check("Revoking something that is not approved is rejected", r.status_code == 409, str(r.status_code))

            print("\n== Duplicate submission merge ==")
            first_id = submission_id
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": "第二次修改"},
            )
            check("Same target reuses the submission", r.json()["submission"]["id"] == first_id, r.text[:200])
            check("Back to pending after edit", r.json()["submission"]["status"] == "pending")

            print("\n== Category aliases ==")
            r = alice.get("/api/categories/lzh")
            new_keys = [*r.json()["category"]["keys"], "smoke_alias"]
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "category"},
                json={"category_id": "小廖", "keys": new_keys, "note": "加个别名"},
            )
            check("Submit alias change", r.status_code == 201, r.text[:300])
            category_submission_id = r.json()["submission"]["id"]

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "category"},
                json={"category_id": "小廖", "keys": [*new_keys, "kepy"], "note": "与别的类别冲突"},
            )
            check("Alias conflicting with another category rejected", r.status_code == 400, r.text[:200])

            r = alice.post(
                "/api/submissions",
                params={"img_key": "__AUDIT__", "type": "category_create"},
                json={"category_id": "保留名", "keys": ["保留名"], "note": ""},
            )
            check("Reserved category key rejected", r.status_code == 400, r.text[:200])

            print("\n== New category ==")
            r = alice.post(
                "/api/submissions",
                params={"img_key": NEW_CATEGORY, "type": "category_create"},
                json={
                    "category_id": "冒烟测试类别",
                    "keys": ["冒烟测试类别", "smoke_cat"],
                    "note": "新建类别",
                },
            )
            check("Submit new category", r.status_code == 201, r.text[:300])
            create_submission_id = r.json()["submission"]["id"]

            r = alice.get("/api/categories")
            check(
                "Pending draft appears in category list",
                any(
                    item["img_key"] == NEW_CATEGORY and item["is_pending_new"]
                    for item in r.json()["categories"]
                ),
            )

            print("\n== Likes and comments ==")
            # 磁盘上已经攒了 40 个赞（Bot 加出来的），这正是旧实现会被上限卡住的场景
            parser_now = read_json(parser_path)
            parser_now[MD5S[1] + ".gif"]["likes"] = 40
            parser_path.write_text(
                json.dumps(parser_now, ensure_ascii=False, indent=4), encoding="utf-8"
            )

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "likes"},
                json={"name": MD5S[1] + ".gif", "likes_delta": 7},
            )
            check("Submit a like increment", r.status_code == 201, r.text[:200])
            likes_submission_id = r.json()["submission"]["id"]
            check(
                "The submission stores the increment, not the total",
                r.json()["submission"]["submitted_value"] == 7
                and r.json()["submission"]["base_value"] == 40,
                r.text[:200],
            )

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "likes"},
                json={"name": MD5S[1] + ".gif", "likes_delta": 11},
            )
            check("One change may not add more than 10", r.status_code == 422, r.text[:200])

            # 编辑表单走的是 /batch（前端实际调用的接口），点赞增量必须同样能提交
            r = alice.post(
                "/api/submissions/batch",
                params={"img_key": "lzh"},
                json={"name": MD5S[3] + ".gif", "likes_delta": 4, "note": "batch 路径"},
            )
            check(
                "Batch submit accepts a like increment",
                r.status_code == 200 and r.json()["created"] == [{"field": "likes"}],
                r.text[:200],
            )
            batch_likes = next(
                item
                for item in alice.get("/api/submissions", params={"status": "pending"}).json()["items"]
                if item["target"] == MD5S[3] + ".gif"
            )
            check(
                "Batch submit stored the increment",
                batch_likes["type"] == "likes" and batch_likes["submitted_value"] == 4,
                json.dumps(batch_likes, ensure_ascii=False),
            )
            alice.delete(f"/api/submissions/{batch_likes['id']}")

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "comments"},
                json={"name": MD5S[1] + ".gif", "comments": ["新评论", "  再 来 一 条  "]},
            )
            check("Submit comments", r.status_code == 201, r.text[:200])
            check(
                "Comments normalized",
                r.json()["submission"]["submitted_value"] == ["新评论", "再 来 一 条"],
                json.dumps(r.json()["submission"]["submitted_value"], ensure_ascii=False),
            )

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "comments"},
                json={"name": MD5S[1] + ".gif", "comments": ["x" * 40]},
            )
            check("Overlong comment rejected", r.status_code == 400, r.text[:200])

            print("\n== One-click apply ==")
            for item in (category_submission_id, create_submission_id, likes_submission_id):
                r = admin_client.post(f"/api/admin/review/{item}", json={"approve": True})
                check(f"Approve submission #{item}", r.status_code == 200, r.text[:200])

            pending = admin_client.get("/api/admin/queue", params={"status": "pending"}).json()
            # Two items should remain pending here: the "second edit" OCR change + the comments submission
            check("Remaining pending count", pending["total"] == 2, str(pending["total"]))
            for item in pending["items"]:
                r = admin_client.post(f"/api/admin/review/{item['id']}", json={"approve": True})
                check(f"Approve submission #{item['id']}", r.status_code == 200, r.text[:200])

            r = admin_client.get("/api/admin/apply/preview")
            preview = r.json()
            check("Apply preview readable", r.status_code == 200, r.text[:300])
            check("Preview entry count", preview["submissions"] == 5, str(preview["submissions"]))
            check(
                "No conflicts in preview",
                not preview["conflicts"],
                json.dumps(preview["conflicts"], ensure_ascii=False),
            )

            r = admin_client.post("/api/admin/apply", json={"dry_run": True})
            check("Dry run succeeded", r.status_code == 200)
            check("Dry run wrote nothing to disk", "第二次修改" not in parser_path.read_text(encoding="utf-8"))

            r = admin_client.post("/api/admin/apply", json={})
            result = r.json()
            check("One-click apply succeeded", r.status_code == 200, r.text[:400])
            check("Applied entry count", result["submissions"] == 5, json.dumps(result, ensure_ascii=False))
            check("New category reported", NEW_CATEGORY in result["new_keys"], str(result["new_keys"]))

            parser_after = read_json(parser_path)
            entry = parser_after[name]
            check("parser.json has the new text written", entry["ocr_text"] == "第二次修改", str(entry))
            check(
                "parser.json field structure complete",
                set(entry) >= {"ocr_text", "add_time", "likes", "comments", "pickup_times"},
                str(sorted(entry)),
            )
            check("Legacy string entry keeps add_time after upgrade", isinstance(entry["add_time"], (int, float)))
            check(
                "Likes added on top of the current total",
                parser_after[MD5S[1] + ".gif"]["likes"] == 47,
                str(parser_after[MD5S[1] + ".gif"]),
            )
            check(
                "Comments written",
                parser_after[MD5S[1] + ".gif"]["comments"] == ["新评论", "再 来 一 条"],
                str(parser_after[MD5S[1] + ".gif"]["comments"]),
            )

            config_after = read_json(config_path)
            check(
                "Alias written to config.json",
                "smoke_alias" in config_after["lzh"]["key"],
                str(config_after["lzh"]),
            )
            check("New category written to config.json", NEW_CATEGORY in config_after, str(sorted(config_after)))
            check("New category directory created", (FIXTURE / NEW_CATEGORY).is_dir())
            check("New category has no parser.json", not (FIXTURE / NEW_CATEGORY / "parser.json").exists())

            r = admin_client.get("/api/admin/queue", params={"status": "applied"})
            check("Applied submissions queryable", r.json()["total"] == 5, str(r.json()["total"]))

            print("\n== Likes: the cap is per change, the total is not capped ==")
            check(
                "A total above the old cap survived the apply",
                read_json(parser_path)[MD5S[1] + ".gif"]["likes"] == 47,
                str(read_json(parser_path)[MD5S[1] + ".gif"]),
            )

            # 再改一次：增量加在现值上，总量继续涨
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "likes"},
                json={"name": MD5S[1] + ".gif", "likes_delta": 10, "note": "再加一次"},
            )
            check("A second increment is accepted", r.status_code == 201, r.text[:200])
            second_likes_id = r.json()["submission"]["id"]
            admin_client.post(f"/api/admin/review/{second_likes_id}", json={"approve": True})
            admin_client.post("/api/admin/apply", json={})
            check(
                "The increment is added on top of the current total",
                read_json(parser_path)[MD5S[1] + ".gif"]["likes"] == 57,
                str(read_json(parser_path)[MD5S[1] + ".gif"]),
            )

            # 增量在审核期间被别人改过原值时不该算冲突：加在现值上就行
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "likes"},
                json={"name": MD5S[1] + ".gif", "likes_delta": 5},
            )
            third_likes_id = r.json()["submission"]["id"]
            admin_client.post(f"/api/admin/review/{third_likes_id}", json={"approve": True})
            parser_now = read_json(parser_path)
            parser_now[MD5S[1] + ".gif"]["likes"] = 100
            parser_path.write_text(
                json.dumps(parser_now, ensure_ascii=False, indent=4), encoding="utf-8"
            )
            r = admin_client.post("/api/admin/apply", json={})
            check(
                "An increment never conflicts with a changed total",
                not r.json()["conflicts"]
                and read_json(parser_path)[MD5S[1] + ".gif"]["likes"] == 105,
                json.dumps(r.json(), ensure_ascii=False),
            )

            # 单次请求的上限：12 还是会被拦下
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "likes"},
                json={"name": MD5S[0] + ".gif", "likes_delta": 12},
            )
            check("A single change may not add more than 10", r.status_code == 422, r.text[:200])

            print("\n== Conflict detection ==")
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": "conflict-text"},
            )
            conflict_id = r.json()["submission"]["id"]
            admin_client.post(f"/api/admin/review/{conflict_id}", json={"approve": True})

            # Simulate the Bot changing the same field after the review
            parser_now = read_json(parser_path)
            parser_now[name]["ocr_text"] = "BOT-REWROTE"
            parser_path.write_text(
                json.dumps(parser_now, ensure_ascii=False, indent=4), encoding="utf-8"
            )

            r = admin_client.post("/api/admin/apply", json={})
            body = r.json()
            check("Conflict detected", len(body["conflicts"]) >= 1, json.dumps(body, ensure_ascii=False))
            check("Conflict writes nothing to disk", read_json(parser_path)[name]["ocr_text"] == "BOT-REWROTE")

            conflict = body["conflicts"][0]
            check(
                "Conflict reports all three values",
                conflict["current_value"] == "BOT-REWROTE"
                and conflict["submitted_value"] == "conflict-text"
                and conflict["base_value"] is not None,
                json.dumps(conflict, ensure_ascii=False),
            )

            # The submission must move to the dedicated `conflict` status
            r = admin_client.get("/api/admin/queue", params={"status": "conflict"})
            check("Conflict queue lists it", r.json()["total"] == 1, str(r.json()["total"]))
            check("Conflict counter populated", r.json()["counts"]["conflict"] == 1, str(r.json()["counts"]))
            check(
                "Not left in the approved queue",
                admin_client.get("/api/admin/queue", params={"status": "approved"}).json()["total"] == 0,
            )

            r = admin_client.get("/api/admin/conflicts")
            check("Dedicated conflicts endpoint", r.status_code == 200 and r.json()["total"] == 1, r.text[:200])

            # A conflicting submission cannot be re-reviewed, only resolved
            r = admin_client.post(f"/api/admin/review/{conflict_id}", json={"approve": True})
            check("Cannot review a conflicted submission", r.status_code == 409, str(r.status_code))

            # Resolution, option A: discard the submission and keep the disk value
            r = admin_client.post(
                f"/api/admin/conflicts/{conflict_id}/resolve", json={"keep_new": False}
            )
            check("Resolve by discarding", r.status_code == 200 and r.json()["resolved"] == "discarded", r.text[:200])
            check("Disk keeps the bot value", read_json(parser_path)[name]["ocr_text"] == "BOT-REWROTE")

            # Resolution, option B: keep the submitted value and overwrite the disk
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": name, "ocr_text": "user-final"},
            )
            keep_id = r.json()["submission"]["id"]
            admin_client.post(f"/api/admin/review/{keep_id}", json={"approve": True})
            parser_now = read_json(parser_path)
            parser_now[name]["ocr_text"] = "BOT-SECOND"
            parser_path.write_text(
                json.dumps(parser_now, ensure_ascii=False, indent=4), encoding="utf-8"
            )
            admin_client.post("/api/admin/apply", json={})
            r = admin_client.post(f"/api/admin/conflicts/{keep_id}/resolve", json={"keep_new": True})
            check("Resolve by keeping the new value", r.status_code == 200 and r.json()["applied"] is True, r.text[:200])
            check("Disk overwritten with the submitted value", read_json(parser_path)[name]["ocr_text"] == "user-final")
            check(
                "Entry structure still intact",
                set(read_json(parser_path)[name])
                >= {"ocr_text", "add_time", "likes", "comments", "pickup_times"},
            )
            check(
                "Conflict queue drained",
                admin_client.get("/api/admin/queue", params={"status": "conflict"}).json()["total"] == 0,
            )

            print("\n== Conflict via category edit ==")
            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "category"},
                json={"category_id": "LZH-renamed", "keys": ["lzh", "lzh-alias"]},
            )
            category_conflict_id = r.json()["submission"]["id"]
            admin_client.post(f"/api/admin/review/{category_conflict_id}", json={"approve": True})

            config_now = read_json(config_path)
            config_now["lzh"]["id"] = "CHANGED-BY-BOT"
            config_path.write_text(
                json.dumps(config_now, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            r = admin_client.post("/api/admin/apply", json={})
            check("Category conflict detected", len(r.json()["conflicts"]) == 1, json.dumps(r.json(), ensure_ascii=False))
            check("config.json untouched", read_json(config_path)["lzh"]["id"] == "CHANGED-BY-BOT")

            r = admin_client.post(
                f"/api/admin/conflicts/{category_conflict_id}/resolve", json={"keep_new": True}
            )
            check("Category conflict resolved", r.status_code == 200, r.text[:200])
            config_after_resolve = read_json(config_path)
            check(
                "Category overwritten by resolution",
                config_after_resolve["lzh"]["id"] == "LZH-renamed"
                and "lzh-alias" in config_after_resolve["lzh"]["key"],
                json.dumps(config_after_resolve["lzh"], ensure_ascii=False),
            )

            print("\n== Same field, two authors ==")
            # 两个人各自基于磁盘原值改同一个字段：一条写盘，另一条转冲突等裁定，
            # 谁也不会被静默覆盖或并进别人的提交里
            same_field_md5 = MD5S[2]
            same_field_name = f"{same_field_md5}.gif"
            before_text = read_json(parser_path)[same_field_name]["ocr_text"]

            r = alice.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": same_field_name, "ocr_text": "alice-version"},
            )
            alice_same_id = r.json()["submission"]["id"]

            r = admin_client.post(
                "/api/submissions",
                params={"img_key": "lzh", "type": "ocr_text"},
                json={"name": same_field_name, "ocr_text": "admin-version"},
            )
            admin_same_id = r.json()["submission"]["id"]
            check(
                "Both edits record the same original value",
                r.json()["submission"]["base_value"] == before_text,
                json.dumps(r.json()["submission"], ensure_ascii=False),
            )

            # 浏览接口要能看到原值 + 每个人的审核中改动（不止一条）
            listing = alice.get(
                "/api/images/lzh", params={"page_size": 100, "q": same_field_md5}
            ).json()["items"][0]
            check(
                "Every in-review change is listed with its author",
                listing["ocr_text"] == before_text
                and [
                    (item["author_name"], item["value"], item["mine"])
                    for item in listing["pending_changes"]
                ]
                == [("Alice", "alice-version", True), ("admin", "admin-version", False)],
                json.dumps(listing["pending_changes"], ensure_ascii=False),
            )

            # 换个视角看：别人的那条 mine=false，自己的那条 mine=true，两条都得在
            admin_view_same = admin_client.get(
                "/api/images/lzh", params={"page_size": 100, "q": same_field_md5}
            ).json()["items"][0]
            check(
                "The other author's change stays visible and is not marked as mine",
                [(item["author_name"], item["mine"]) for item in admin_view_same["pending_changes"]]
                == [("Alice", False), ("admin", True)],
                json.dumps(admin_view_same["pending_changes"], ensure_ascii=False),
            )

            for item in (alice_same_id, admin_same_id):
                admin_client.post(f"/api/admin/review/{item}", json={"approve": True})
            r = admin_client.post("/api/admin/apply", json={})
            check(
                "The first change lands and the second is held as a conflict",
                read_json(parser_path)[same_field_name]["ocr_text"] == "alice-version"
                and [item["submission_id"] for item in r.json()["conflicts"]] == [admin_same_id],
                json.dumps(r.json(), ensure_ascii=False),
            )

            r = admin_client.post(
                f"/api/admin/conflicts/{admin_same_id}/resolve", json={"keep_new": False}
            )
            check("Nothing is silently merged", r.status_code == 200, r.text[:200])
            check(
                "The first author's change is still the disk value",
                read_json(parser_path)[same_field_name]["ocr_text"] == "alice-version",
                str(read_json(parser_path)[same_field_name]),
            )

            # 类别同理：两个人的改动不能被折叠成一份
            r = alice.post(
                "/api/submissions",
                params={"img_key": "kepy", "type": "category"},
                json={"category_id": "kepy-alice", "keys": ["kepy", "kepy-a"]},
            )
            alice_cat_id = r.json()["submission"]["id"]
            r = admin_client.post(
                "/api/submissions",
                params={"img_key": "kepy", "type": "category"},
                json={"category_id": "kepy-admin", "keys": ["kepy", "kepy-b"]},
            )
            admin_cat_id = r.json()["submission"]["id"]

            for item in (alice_cat_id, admin_cat_id):
                admin_client.post(f"/api/admin/review/{item}", json={"approve": True})
            r = admin_client.post("/api/admin/apply", json={})
            check(
                "Two category edits are not folded into one",
                read_json(config_path)["kepy"]["id"] == "kepy-alice"
                and [item["submission_id"] for item in r.json()["conflicts"]] == [admin_cat_id],
                json.dumps(r.json(), ensure_ascii=False),
            )
            admin_client.post(
                f"/api/admin/conflicts/{admin_cat_id}/resolve", json={"keep_new": False}
            )

            print("\n== Withdraw ==")
            r = alice.post(
                "/api/submissions",
                params={"img_key": "kepy", "type": "likes"},
                json={"name": MD5S[0] + ".gif", "likes_delta": 3},
            )
            check("Submit for an image missing from parser", r.status_code == 201, r.text[:300])
            withdraw_id = r.json()["submission"]["id"]
            r = alice.delete(f"/api/submissions/{withdraw_id}")
            check("Withdraw own submission", r.status_code == 200, r.text[:200])
            r = alice.delete(f"/api/submissions/{conflict_id}")
            check("Withdrawing a reviewed submission rejected", r.status_code in (400, 403), str(r.status_code))

            print("\n== Accounts and admin ==")
            r = admin_client.get("/api/admin/users")
            users = r.json()["users"]
            check("Account list", r.status_code == 200 and len(users) == 2, r.text[:200])
            alice_id = next(item["id"] for item in users if item["username"] == "alice")
            admin_id = next(item["id"] for item in users if item["username"] == "admin")

            r = admin_client.patch(f"/api/admin/users/{alice_id}", json={"is_active": False})
            check("Deactivate account", r.status_code == 200, r.text[:200])
            check("Session invalid after deactivation", alice.get("/api/auth/me").status_code == 401)
            admin_client.patch(f"/api/admin/users/{alice_id}", json={"is_active": True})

            r = admin_client.patch(f"/api/admin/users/{admin_id}", json={"is_active": False})
            check("Cannot deactivate yourself", r.status_code == 400, r.text[:200])
            r = admin_client.patch(f"/api/admin/users/{admin_id}", json={"role": "user"})
            check("Cannot change your own role", r.status_code == 400, r.text[:200])

            r = admin_client.post(
                "/api/admin/users",
                json={"username": "bob", "password": "bob12345678", "role": "user"},
            )
            check("Admin creates account", r.status_code == 201, r.text[:200])

            r = admin_client.get("/api/admin/logs")
            check("Audit log", r.status_code == 200 and r.json()["total"] > 0, r.text[:200])

            r = admin_client.get("/api/admin/integrity")
            integrity = r.json()
            lzh_report = next(item for item in integrity["categories"] if item["img_key"] == "lzh")
            check(
                "Integrity endpoint",
                r.status_code == 200 and lzh_report["images"] == 8,
                json.dumps(lzh_report),
            )
            kepy_report = next(item for item in integrity["categories"] if item["img_key"] == "kepy")
            check(
                "Integrity check finds images missing from parser",
                kepy_report["image_without_parser"] == 1,
                json.dumps(kepy_report),
            )

            r = admin_client.get("/api/admin/overview")
            counts = r.json()["submission_counts"]
            check(
                "Admin overview counts every status",
                r.status_code == 200
                and counts["conflict"] == 0
                and counts["applied"] >= 7
                and r.json()["approved_total"] == 0,
                r.text[:300],
            )

            r = admin_client.get("/api/meta/info")
            check("Runtime info", r.status_code == 200 and r.json()["lib_available"], r.text[:200])

            print("\n== Change password ==")
            bob.post("/api/auth/login", json={"username": "bob", "password": "bob12345678"})
            r = bob.post(
                "/api/auth/password",
                json={"old_password": "bob12345678", "new_password": "bob87654321"},
            )
            check("Change password", r.status_code == 200, r.text[:200])
            bob.post("/api/auth/logout")
            r = bob.post("/api/auth/login", json={"username": "bob", "password": "bob87654321"})
            check("Can log in with the new password", r.status_code == 200, r.text[:200])

            r = admin_client.post("/api/auth/logout")
            check("Logout", r.status_code == 200)
            check("Session invalid after logout", admin_client.get("/api/auth/me").status_code == 401)

    finally:
        config_path.write_text(config_before, encoding="utf-8")
        parser_path.write_text(parser_before, encoding="utf-8")
        shutil.rmtree(DATA_DIR, ignore_errors=True)

    print(f"\n{'=' * 60}\npassed {len(PASSED)}, failed {len(FAILED)}")
    if FAILED:
        print("Failed:")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
