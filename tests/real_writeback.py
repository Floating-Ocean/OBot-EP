"""A full write-back rehearsal against OBot-ACM real data over HTTP.

Temporarily modifies the orzjh category (only 1 image, and it uses the legacy string
structure), and restores it immediately after verification.
Requires a writable Python environment (because it really writes to ../OBot-ACM/lib/Pick-One).

Run:
  .venv\\Scripts\\python.exe tests\\real_writeback.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Accounts live in a local temporary store so real runtime data is not polluted
os.environ.setdefault("OBOT_EP_DATA_DIR", str(ROOT / ".tmp" / "writeback-data"))
os.environ.setdefault("OBOT_EP_ADMIN_USER", "wbadmin")
os.environ.setdefault("OBOT_EP_ADMIN_PASSWORD", "wbadmin12345")

LIB = ROOT.parent / "OBot-ACM" / "lib" / "Pick-One"
CATEGORY = "orzjh"

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
    from fastapi.testclient import TestClient

    from server.app import app
    from server.repository import ROLE_ADMIN

    parser_path = LIB / CATEGORY / "parser.json"
    config_path = LIB / "config.json"
    parser_before = parser_path.read_text(encoding="utf-8")
    config_before = config_path.read_text(encoding="utf-8")
    original = json.loads(parser_before)
    name = next(iter(original))

    print(f"Target: {CATEGORY}/{name} (original value is a string: {isinstance(original[name], str)})\n")

    try:
        admin = TestClient(app)
        user = TestClient(app)
        with admin, user:
            # The first account in the temporary store is created automatically by lifespan,
            # but make sure it is an admin just in case
            repo = app.state.repo
            account = repo.get_user_by_username(os.environ["OBOT_EP_ADMIN_USER"])
            if account is not None:
                repo.set_user_role(int(account["id"]), ROLE_ADMIN)

            r = admin.post(
                "/api/auth/login",
                json={
                    "username": os.environ["OBOT_EP_ADMIN_USER"],
                    "password": os.environ["OBOT_EP_ADMIN_PASSWORD"],
                },
            )
            check("admin login", r.status_code == 200, r.text[:200])

            r = user.post(
                "/api/auth/register",
                json={
                    "username": "realcheck",
                    "password": "realcheck123",
                    "display_name": "Real check",
                },
            )
            if r.status_code == 400:
                r = user.post(
                    "/api/auth/login",
                    json={"username": "realcheck", "password": "realcheck123"},
                )
            check("regular user available", r.status_code in (200, 201), r.text[:200])

            print("\n== Submit ==")
            r = user.post(
                "/api/submissions",
                params={"img_key": CATEGORY, "type": "ocr_text"},
                json={"name": name, "ocr_text": "实机写回验证文本", "note": "Automated check"},
            )
            check("submit OCR change", r.status_code == 201, r.text[:300])
            submission_id = r.json()["submission"]["id"]

            r = user.post(
                "/api/submissions",
                params={"img_key": CATEGORY, "type": "comments"},
                json={"name": name, "comments": ["实机核对评论"]},
            )
            check("submit comments", r.status_code == 201, r.text[:300])
            comments_id = r.json()["submission"]["id"]

            check("disk unchanged before review", parser_path.read_text(encoding="utf-8") == parser_before)

            print("\n== Review ==")
            for item in (submission_id, comments_id):
                r = admin.post(f"/api/admin/review/{item}", json={"approve": True})
                check(f"approve #{item}", r.status_code == 200, r.text[:200])
            check("disk still unchanged after approval", parser_path.read_text(encoding="utf-8") == parser_before)

            print("\n== One-click apply ==")
            r = admin.post("/api/admin/apply", json={})
            result = r.json()
            check("apply succeeded", r.status_code == 200, r.text[:400])
            check("wrote 2 image fields", result["applied_images"] == 2, json.dumps(result, ensure_ascii=False))
            check("no conflicts", not result["conflicts"], json.dumps(result["conflicts"], ensure_ascii=False))

            after = json.loads(parser_path.read_text(encoding="utf-8"))
            entry = after[name]
            check("entry upgraded to a dict", isinstance(entry, dict), str(type(entry)))
            check("ocr_text written", entry["ocr_text"] == "实机写回验证文本", str(entry))
            check("comments written", entry["comments"] == ["实机核对评论"], str(entry))
            check(
                "all five fields present",
                set(entry) >= {"ocr_text", "add_time", "likes", "comments", "pickup_times"},
                str(sorted(entry)),
            )
            check("add_time has a value", float(entry["add_time"]) > 0, str(entry.get("add_time")))
            check("no entries added or lost", set(after) == set(original), str(set(after) ^ set(original)))

            print("\n== UI read ==")
            r = user.get(f"/api/images/{CATEGORY}/item/{name}")
            check(
                "details reflect the new values",
                r.json()["image"]["ocr_text"] == "实机写回验证文本",
                r.text[:200],
            )
            check("no longer flagged as legacy format", not r.json()["image"]["legacy"])

            r = admin.get("/api/admin/integrity")
            report = next(item for item in r.json()["categories"] if item["img_key"] == CATEGORY)
            check("integrity report shows alignment", report["parser_without_image"] == 0, json.dumps(report))

    finally:
        parser_path.write_text(parser_before, encoding="utf-8")
        config_path.write_text(config_before, encoding="utf-8")
        restored = json.loads(parser_path.read_text(encoding="utf-8"))
        same = isinstance(restored.get(name), str) and restored == original
        print(f"\nRestored {CATEGORY}/parser.json and config.json (content identical: {same})")
        check("restore succeeded", same)

    print(f"\n{'=' * 60}\npassed {len(PASSED)}, failed {len(FAILED)}")
    if FAILED:
        for item in FAILED:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
