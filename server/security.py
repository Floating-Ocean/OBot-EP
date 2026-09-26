"""口令哈希与会话令牌。

刻意只用标准库：PBKDF2-HMAC-SHA256 存口令，HMAC-SHA256 签会话令牌。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from . import config

_PBKDF2_ROUNDS = 260_000
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """返回 `pbkdf2_sha256$rounds$salt_b64$hash_b64` 形式的口令摘要。"""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ROUNDS)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(_PBKDF2_ROUNDS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded: str) -> bool:
    """恒定时间校验口令。"""
    if not password or not encoded:
        return False
    try:
        algorithm, rounds_raw, salt_b64, digest_b64 = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        rounds = int(rounds_raw)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _sign(payload: bytes) -> str:
    return _b64url_encode(
        hmac.new(config.SESSION_SECRET.encode("utf-8"), payload, hashlib.sha256).digest()
    )


def create_session_token(user_id: int, username: str, role: str) -> str:
    """签发会话令牌（无状态，服务端不落库）。"""
    payload = {
        "uid": user_id,
        "u": username,
        "r": role,
        "exp": int(time.time()) + config.SESSION_TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = _b64url_encode(raw)
    return f"{body}.{_sign(raw)}"


def parse_session_token(token: str | None) -> dict | None:
    """校验并解出会话令牌，失败返回 None。"""
    if not token or token.count(".") != 1:
        return None

    body, signature = token.split(".", 1)
    try:
        raw = _b64url_decode(body)
    except (ValueError, TypeError):
        return None

    if not hmac.compare_digest(_sign(raw), signature):
        return None

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None

    if not isinstance(payload, dict) or int(payload.get("exp", 0)) < time.time():
        return None
    return payload


def generate_password(length: int = 12) -> str:
    """生成随机初始口令。"""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
