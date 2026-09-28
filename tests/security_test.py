"""Security regression checks for the fixes applied to OBot-EP.

Each check pins one specific hole that was found during the security review, so a
future refactor that re-opens it fails loudly instead of silently.

Run: .venv\\Scripts\\python.exe tests\\security_test.py
"""

from __future__ import annotations

import io
import os
import shutil
import sqlite3
import sys
import time
import unittest.mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / ".tmp" / "security-fixture"
DATA_DIR = ROOT / ".tmp" / "security-data"

os.environ["OBOT_PICK_ONE_DIR"] = str(FIXTURE)
os.environ["OBOT_EP_DATA_DIR"] = str(DATA_DIR)
os.environ["OBOT_EP_ADMIN_PASSWORD"] = "admin12345"
os.environ["OBOT_EP_SECRET"] = "security-test-secret"
# 登录预算放宽：本文件里有好几处正常登录，真正测限速的部分用独立的
# RateLimiter 实例做（见 test_rate_limiter_unit），免得测试之间互相踩
os.environ["OBOT_EP_LOGIN_MAX"] = "24"
os.environ["OBOT_EP_LOGIN_WINDOW"] = "300"
# A tiny pixel budget so the decompression-bomb guard trips on a small fixture
os.environ["OBOT_EP_THUMB_MAX_PIXELS"] = "2000"

# 中文提示在 GBK 控制台上会乱码，也方便断言里比对中文文案
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from PIL import Image  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server import config  # noqa: E402
from server.api import auth as auth_api  # noqa: E402
from server.app import app  # noqa: E402
from server.hashing import ThumbnailError, make_thumbnail  # noqa: E402
from server.ratelimit import RateLimiter  # noqa: E402
from server.repository import Repository  # noqa: E402
from server.security import hash_password, parse_session_token, verify_password  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []

MD5 = "0f1e2d3c4b5a69788796a5b4c3d2e1f0"
CATEGORY = "sec"


def check(label: str, condition: bool, extra: str = "") -> None:
    if condition:
        PASSED.append(label)
        print(f"  [PASS] {label}")
    else:
        FAILED.append(label)
        print(f"  [FAIL] {label} {extra}")


def build_fixture() -> None:
    shutil.rmtree(FIXTURE, ignore_errors=True)
    shutil.rmtree(DATA_DIR, ignore_errors=True)

    (FIXTURE / CATEGORY).mkdir(parents=True)
    image = Image.new("RGB", (60, 60), (200, 60, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="GIF")
    (FIXTURE / CATEGORY / f"{MD5}.gif").write_bytes(buffer.getvalue())
    (FIXTURE / CATEGORY / "parser.json").write_text("{}", encoding="utf-8")
    (FIXTURE / "config.json").write_text(
        '{"%s": {"id": "安全", "key": ["安全", "sec"]}}' % CATEGORY, encoding="utf-8"
    )


def test_password_and_rounds() -> None:
    print("\n== Password hashing ==")
    encoded = hash_password("correct horse battery")
    check("Round trip verifies", verify_password("correct horse battery", encoded))
    check("Wrong password rejected", not verify_password("nope", encoded))

    # 摘要里的 rounds 是数据库里的数据；一个被写坏的天文数字能让一次登录占死 CPU
    tampered = encoded.split("$")
    tampered[1] = "900000000"
    check(
        "Absurd stored round count is refused",
        not verify_password("correct horse battery", "$".join(tampered)),
    )
    tampered[1] = "1"
    check(
        "Below-minimum round count is refused",
        not verify_password("correct horse battery", "$".join(tampered)),
    )


def test_thumbnail_bomb() -> None:
    print("\n== Thumbnail limits ==")
    # 400x400 = 160000 像素，远大于本测试设的 2000 上限
    big = Image.new("RGB", (400, 400), (10, 200, 10))
    buffer = io.BytesIO()
    big.save(buffer, format="GIF")

    try:
        make_thumbnail(buffer.getvalue())
    except ThumbnailError:
        check("Oversized image raises ThumbnailError instead of eating memory", True)
    except Exception as error:  # pragma: no cover - would be a regression
        check("Oversized image raises ThumbnailError instead of eating memory", False, repr(error))
    else:
        check(
            "Oversized image raises ThumbnailError instead of eating memory",
            False,
            "no error raised",
        )


def test_csrf_origin() -> None:
    print("\n== CSRF origin guard ==")
    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin12345"},
            headers={"origin": "http://evil.example"},
        )
        check("Cross-site login rejected", r.status_code == 403, r.text[:200])

        r = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin12345"},
            headers={"origin": "null"},
        )
        check("Origin: null rejected", r.status_code == 403, r.text[:200])

        r = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin12345"},
            headers={"origin": "http://testserver"},
        )
        check("Same-origin login accepted", r.status_code == 200, r.text[:200])

        r = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin12345"},
            headers={"referer": "http://evil.example/login"},
        )
        check("Cross-site referer rejected", r.status_code == 403, r.text[:200])

        r = client.get("/api/categories", headers={"origin": "http://evil.example"})
        check("Read-only cross-site GET still allowed", r.status_code == 200, r.text[:200])


def test_session_invalidation() -> None:
    """两个浏览器 = 同一个客户端上换 Cookie。

    注意不要嵌套两个 `TestClient` 上下文：app 是模块级单例，每次进入 lifespan
    都会换掉 app.state.repo，先退出的那个会把后退出者的数据库连接一起关掉。
    """
    print("\n== Sessions follow the password ==")
    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"}
        )
        check("First browser logs in", r.status_code == 200, r.text[:200])
        first_cookie = client.cookies.get(config.SESSION_COOKIE)

        client.cookies.clear()
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"}
        )
        check("Second browser logs in", r.status_code == 200, r.text[:200])

        r = client.post(
            "/api/auth/password",
            json={"old_password": "admin12345", "new_password": "admin67890"},
        )
        check("Password changed", r.status_code == 200, r.text[:200])

        r = client.get("/api/auth/me")
        check("Changing browser stays logged in", r.status_code == 200, r.text[:200])

        # 换回改密之前那张票，它必须已经作废
        client.cookies.clear()
        client.cookies.set(config.SESSION_COOKIE, first_cookie)
        r = client.get("/api/auth/me")
        check(
            "Other sessions are invalidated by the password change",
            r.status_code == 401,
            str(r.status_code),
        )

        client.cookies.clear()
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin67890"}
        )
        check("New password works", r.status_code == 200, r.text[:200])
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin12345"}
        )
        check("Old password no longer works", r.status_code == 401, str(r.status_code))


def test_public_endpoints() -> None:
    print("\n== Public endpoints stay quiet ==")
    with TestClient(app) as client:
        r = client.get("/api/health")
        body = r.text
        check(
            "Health check has no filesystem path",
            r.status_code == 200 and str(config.PICK_ONE_DIR) not in body and "lib" not in body,
            body[:200],
        )

        r = client.get("/api/meta/versions")
        data = r.json()
        check(
            "Public version endpoint drops the commit hash",
            r.status_code == 200 and "commit" not in data,
            str(data),
        )

        r = client.get("/api/meta/info")
        check("Runtime info still requires login", r.status_code == 401, str(r.status_code))


def test_input_validation() -> None:
    print("\n== Input validation ==")
    with TestClient(app) as client:
        # 这一步跑在改密用例之后，所以用的是改后的口令
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin67890"}
        )
        check("Admin login for validation checks", r.status_code == 200, r.text[:200])

        r = client.get("/api/submissions", params={"status": "all", "img_key": "../" * 10})
        check(
            "Traversal-ish img_key filter is not a server error",
            r.status_code == 200,
            str(r.status_code),
        )

        r = client.get(f"/api/images/{'a' * 300}/stats")
        check(
            "Over-long category id is refused without touching the filesystem",
            r.status_code in (404, 414),
            str(r.status_code),
        )

        r = client.get(f"/api/images/{CATEGORY}/hash-id/{'z' * 5000}")
        check(
            "Over-long hash id is refused",
            r.status_code in (400, 414),
            str(r.status_code),
        )

        r = client.post("/api/admin/review/batch", json={"ids": "not-a-list", "approve": True})
        check(
            "Malformed batch review body is a 422, not a 500",
            r.status_code == 422,
            str(r.status_code),
        )

        r = client.get(f"/api/images/{CATEGORY}/thumb/../../config.json")
        check(
            "Thumbnail path traversal is refused",
            r.status_code == 404,
            str(r.status_code),
        )


def test_rate_limiter_unit() -> None:
    """直接测限速器本身：走 HTTP 测会污染其它用例的登录预算。"""
    print("\n== Rate limiter ==")
    limiter = RateLimiter(limit=3, window_seconds=60)
    check("First hit allowed", limiter.retry_after("k") == 0)
    limiter.record("k")
    check("Second hit allowed", limiter.retry_after("k") == 0)
    limiter.record("k")
    limiter.record("k")
    check("Over-budget key is blocked", limiter.retry_after("k") > 0)
    check("Other keys are unaffected", limiter.retry_after("other") == 0)
    limiter.clear("k")
    check("Clearing a key unblocks it", limiter.retry_after("k") == 0)

    disabled = RateLimiter(limit=0, window_seconds=60)
    check("Limit 0 disables the limiter", not disabled.enabled and disabled.retry_after("k") == 0)

    expired = RateLimiter(limit=1, window_seconds=0.05)
    expired.record("k")
    check("Key is blocked inside the window", expired.retry_after("k") > 0)
    time.sleep(0.1)
    check("Key frees up after the window", expired.retry_after("k") == 0)


def test_login_rate_limit_response() -> None:
    """走一次真实的 429，确认状态码与 Retry-After 头都对。

    用假的限速器替换掉全局实例，免得把本进程的登录预算烧掉。
    """
    print("\n== Login rate limit response ==")

    class AlwaysBlocked:
        enabled = True

        def retry_after(self, _key):
            return 42

        def record(self, _key):
            raise AssertionError("blocked requests must not be recorded")

        def clear(self, _key):
            pass

    mock = unittest.mock
    with mock.patch.object(auth_api, "_login_by_ip", AlwaysBlocked()), mock.patch.object(
        auth_api, "_login_by_user", AlwaysBlocked()
    ):
        with TestClient(app) as client:
            r = client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin67890"}
            )
            check("Rate-limited login returns 429", r.status_code == 429, str(r.status_code))
            check(
                "429 carries the Retry-After header",
                r.headers.get("retry-after") == "42",
                str(r.headers.get("retry-after")),
            )

    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login", json={"username": "admin", "password": "admin67890"}
        )
        check("Real limiter is restored afterwards", r.status_code == 200, r.text[:200])


def test_client_address_resolution() -> None:
    """限速对象的地址解析：默认不信转发头，开了 TRUST_PROXY 才信。"""
    print("\n== Client address resolution ==")

    class FakeRequest:
        def __init__(self, headers, client_host="10.0.0.9"):
            self.headers = headers
            self.client = type("C", (), {"host": client_host})()

    spoofed = FakeRequest(
        {"x-forwarded-for": "1.2.3.4", "x-real-ip": "5.6.7.8"}, client_host="10.0.0.9"
    )
    check(
        "Forwarded headers are ignored by default",
        auth_api._client_key(spoofed) == "10.0.0.9",
        auth_api._client_key(spoofed),
    )

    original = config.TRUST_PROXY
    original_ips = config.TRUSTED_PROXY_IPS
    try:
        config.TRUST_PROXY = True
        check(
            "X-Forwarded-For is honoured when explicitly enabled",
            auth_api._client_key(spoofed) == "1.2.3.4",
            auth_api._client_key(spoofed),
        )

        config.TRUSTED_PROXY_IPS = frozenset({"10.0.0.9"})
        chained = FakeRequest({"x-forwarded-for": "9.9.9.9, 1.2.3.4, 10.0.0.9"})
        check(
            "Trusted proxy hops are skipped from the right",
            auth_api._client_key(chained) == "1.2.3.4",
            auth_api._client_key(chained),
        )

        real_only = FakeRequest({"x-real-ip": "7.7.7.7"})
        check(
            "X-Real-IP is used as a fallback",
            auth_api._client_key(real_only) == "7.7.7.7",
            auth_api._client_key(real_only),
        )

        config.TRUST_PROXY = False
        check(
            "Turning the flag back off ignores the header again",
            auth_api._client_key(spoofed) == "10.0.0.9",
            auth_api._client_key(spoofed),
        )
    finally:
        config.TRUST_PROXY = original
        config.TRUSTED_PROXY_IPS = original_ips


def test_session_token_parsing() -> None:
    """回归：非 ASCII 的 Cookie 值过去会让 hmac.compare_digest 抛 TypeError（500）。"""
    print("\n== Session token parsing ==")
    tampered = f"YWJj.{chr(255)}"
    check(
        "Non-ASCII signature is rejected instead of raising",
        parse_session_token(tampered) is None,
    )
    check("Empty token rejected", parse_session_token("") is None)
    check("No-dot token rejected", parse_session_token("abc") is None)
    check("Non-dict payload rejected", parse_session_token("WzFd." + "x" * 43) is None)


def test_malformed_origin_does_not_500() -> None:
    """回归：Origin 的端口越界会让 urlsplit(...).port 抛 ValueError（500）。"""
    print("\n== Malformed Origin ==")
    with TestClient(app) as client:
        r = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "admin67890"},
            headers={"origin": "http://x:99999", "host": "testserver"},
        )
        check(
            "Malformed Origin header does not 500",
            r.status_code == 403,
            f"{r.status_code} {r.text[:120]}",
        )


def test_body_size_limit() -> None:
    print("\n== Request body limit ==")
    with TestClient(app) as client:
        huge = "a" * (config.MAX_REQUEST_BODY_BYTES + 1024)
        r = client.post(
            "/api/auth/login", json={"username": huge, "password": huge}
        )
        check(
            "Oversized body is rejected before parsing",
            r.status_code == 413,
            str(r.status_code),
        )


def test_category_key_case() -> None:
    """回归：NTFS/macOS 不区分大小写，大小写不同的「新类别」会撞进同一个目录。"""
    print("\n== Category key casing ==")
    with TestClient(app) as client:
        r = client.post("/api/auth/login", json={"username": "admin", "password": "admin67890"})
        check("Admin login for category checks", r.status_code == 200, r.text[:200])

        r = client.post(
            "/api/submissions",
            params={"img_key": CATEGORY.upper(), "type": "category_create"},
            json={"category_id": "新类别", "keys": ["另起一个别名"]},
        )
        check(
            "Case-variant of an existing key is refused",
            r.status_code == 400,
            f"{r.status_code} {r.text[:200]}",
        )


def test_delete_user_with_history() -> None:
    """回归：DELETE /admin/users/{id} 过去总是 500（外键 RESTRICT）。

    同一个客户端换 Cookie 扮演不同账号，避免嵌套 TestClient（见 session 用例的说明）。
    """
    print("\n== Deleting accounts ==")
    with TestClient(app) as client:
        def login(name: str, password: str):
            client.cookies.clear()
            return client.post(
                "/api/auth/login", json={"username": name, "password": password}
            )

        def as_admin():
            return login("admin", "admin67890")

        r = as_admin()
        check("Admin login for account checks", r.status_code == 200, r.text[:200])

        users = client.get("/api/admin/users").json()["users"]
        admin_id = next(item["id"] for item in users if item["username"] == "admin")

        r = client.delete(f"/api/admin/users/{admin_id}")
        check("Self-deletion still refused", r.status_code == 400, str(r.status_code))

        # 造一个有提交历史、但已停用的账号：删除应当被明确拒绝（409），而不是 500
        r = client.post(
            "/api/admin/users",
            json={"username": "ghost", "password": "ghost12345", "role": "user"},
        )
        check("Second account created", r.status_code == 201, r.text[:200])
        ghost_id = r.json()["user"]["id"]

        r = login("ghost", "ghost12345")
        check("Ghost logs in", r.status_code == 200, r.text[:200])
        r = client.post(
            "/api/submissions",
            params={"img_key": CATEGORY, "type": "likes"},
            json={"name": f"{MD5}.gif", "likes_delta": 1},
        )
        check("Ghost submits something", r.status_code == 201, r.text[:200])

        as_admin()
        client.patch(f"/api/admin/users/{ghost_id}", json={"is_active": False})
        r = client.delete(f"/api/admin/users/{ghost_id}")
        check(
            "Account with history is refused with a reason, not a 500",
            r.status_code == 409,
            f"{r.status_code} {r.text[:200]}",
        )

        # 没有历史的账号仍然可以删除
        r = client.post(
            "/api/admin/users",
            json={"username": "clean", "password": "clean12345", "role": "user"},
        )
        clean_id = r.json()["user"]["id"]
        r = client.delete(f"/api/admin/users/{clean_id}")
        check("Account without history is deleted", r.status_code == 200, r.text[:200])
        check(
            "Audit log survives the deletion",
            any(
                item["action"] == "delete_user"
                for item in client.get("/api/admin/logs").json()["items"]
            ),
            "",
        )


def test_stray_gif_does_not_break_listing() -> None:
    """回归：目录里混进非 MD5 命名的 .gif 会让整个类别列表 500。"""
    print("\n== Stray files in the category dir ==")
    stray = FIXTURE / CATEGORY / "not-a-hash.gif"
    stray.write_bytes(b"GIF89a")
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin67890"}
            )
            r = client.get("/api/categories")
            check(
                "Category list survives a stray .gif",
                r.status_code == 200,
                f"{r.status_code} {r.text[:200]}",
            )
            r = client.get(f"/api/images/{CATEGORY}")
            names = [item["name"] for item in r.json().get("items", [])]
            check(
                "Stray file is not listed as an image",
                r.status_code == 200 and "not-a-hash.gif" not in names,
                str(names),
            )
    finally:
        stray.unlink(missing_ok=True)


def test_thumbnail_cache_integrity() -> None:
    """回归：截断的缓存 WebP 会被当成命中，浏览器一直拿到坏图。"""
    import re

    print("\n== Thumbnail cache ==")
    # 本文件的 THUMB_MAX_PIXELS 被刻意设得很小（2000），比 fixture 的 60x60 还低，
    # 所以这里把 Pillow 的像素上限临时调高，单独测缓存逻辑
    original_pixels = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = 10_000_000
    try:
        with TestClient(app) as client:
            client.post(
                "/api/auth/login", json={"username": "admin", "password": "admin67890"}
            )
            first = client.get(f"/api/images/{CATEGORY}/thumb/{MD5}.gif")
            check("Thumbnail generated", first.status_code == 200, first.text[:120])

            cached = list(config.THUMB_DIR.glob("*.webp"))
            check("Thumbnail was cached on disk", len(cached) == 1, str(cached))
            if not cached:
                return
            cache_path = cached[0]

            # 模拟上次写入时被截断/写坏：带上正确的 RIFF 头，但长度不符
            original = cache_path.read_bytes()
            cache_path.write_bytes(original[: len(original) // 2])

            rebuilt = client.get(f"/api/images/{CATEGORY}/thumb/{MD5}.gif")
            check(
                "Corrupt cache entry is not served",
                rebuilt.status_code == 200 and rebuilt.content != original[: len(original) // 2],
                str(rebuilt.status_code),
            )

            cache_path.write_bytes(b"RIFF\x00\x00\x00\x00WEBP")
            header_only = client.get(f"/api/images/{CATEGORY}/thumb/{MD5}.gif")
            check(
                "Header-only cache entry is not served",
                header_only.status_code == 200 and len(header_only.content) > 16,
                str(len(header_only.content)),
            )

            pattern = re.compile(
                re.escape(str(cache_path.stem)) + r"\.[0-9]+\.[0-9]+\.[0-9a-f]+\.tmp$"
            )
            leftovers = [
                item for item in config.THUMB_DIR.iterdir() if pattern.match(item.name)
            ]
            check("No temp files left behind", not leftovers, str(leftovers))

            cache_path.unlink(missing_ok=True)
    finally:
        Image.MAX_IMAGE_PIXELS = original_pixels


def test_audit_log_migration() -> None:
    """回归：老库的 audit_logs 外键是 RESTRICT，删账号会被外键挡住。

    CREATE TABLE IF NOT EXISTS 不会改已存在的表，所以这里手工造一个 0.1.0 时期
    结构的库，确认 Repository 打开时会把外键迁成 ON DELETE SET NULL。
    """
    print("\n== audit_logs migration ==")
    db_path = DATA_DIR / "legacy.sqlite3"
    db_path.unlink(missing_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT    NOT NULL UNIQUE,
            display_name  TEXT    NOT NULL DEFAULT '',
            password_hash TEXT    NOT NULL,
            role          TEXT    NOT NULL DEFAULT 'user',
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    REAL    NOT NULL,
            last_login_at REAL
        );
        CREATE TABLE audit_logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id   INTEGER REFERENCES users(id),
            action     TEXT    NOT NULL,
            detail     TEXT    NOT NULL DEFAULT '',
            created_at REAL    NOT NULL,
            is_admin   INTEGER NOT NULL DEFAULT 0,
            username   TEXT    NOT NULL DEFAULT ''
        );
        """
    )
    conn.commit()
    conn.close()

    repo = Repository(db_path)
    try:
        user = repo.create_user("legacyuser", "legacy12345")
        repo.add_log(
            actor_id=user.id, username=user.username, action="login", detail="legacy row"
        )
        repo.delete_user(user.id)
        logs, total = repo.list_logs(limit=10)
        check("Account with only audit history can be deleted", repo.get_user(user.id) is None)
        check(
            "Audit row survives with a null actor",
            total == 1 and logs[0]["actor_id"] is None,
            str(logs),
        )
    finally:
        repo.close()
        db_path.unlink(missing_ok=True)


def test_docs_are_disabled() -> None:
    """回归：/docs、/redoc、/openapi.json 默认不得注册。

    绑定 0.0.0.0 之后这三个接口不需要登录就能把整套接口面交出去，
    所以默认关闭，只有 OBOT_EP_ENABLE_DOCS=1 时才开放。
    """
    print("\n== API docs are off by default ==")
    registered = {
        getattr(route, "path", "")
        for route in app.routes
        if getattr(route, "path", None)
    }
    for path in ("/docs", "/redoc", "/openapi.json"):
        check(f"{path} is not registered", path not in registered, str(sorted(registered))[:200])

    with TestClient(app) as client:
        r = client.get("/api/auth/config")
        check("Login page config still works", r.status_code == 200, str(r.status_code))


def main() -> int:
    build_fixture()
    try:
        test_password_and_rounds()
        test_thumbnail_bomb()
        test_csrf_origin()
        test_public_endpoints()
        test_docs_are_disabled()
        # 改密用例会改掉 admin 的口令，必须排在需要登录的用例之前
        test_session_invalidation()
        test_input_validation()
        test_rate_limiter_unit()
        test_login_rate_limit_response()
        test_client_address_resolution()
        test_malformed_origin_does_not_500()
        test_session_token_parsing()
        test_body_size_limit()
        test_category_key_case()
        test_delete_user_with_history()
        test_stray_gif_does_not_break_listing()
        test_thumbnail_cache_integrity()
        test_audit_log_migration()
    finally:
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        shutil.rmtree(FIXTURE, ignore_errors=True)

    print(f"\n{'=' * 60}\npassed {len(PASSED)}, failed {len(FAILED)}")
    if FAILED:
        print("Failed:")
        for item in FAILED:
            print(f"  - {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
