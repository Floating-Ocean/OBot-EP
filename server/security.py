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

# 校验口令时接受的迭代次数区间。摘要是数据库里的数据，一旦被写坏（或被塞进一个
# 天文数字的 rounds），一次登录就能把 CPU 占死，所以这里要有上限。
# 下限保证老数据仍能登录，上限留足将来提升强度的空间。
MIN_PBKDF2_ROUNDS = 1_000
MAX_PBKDF2_ROUNDS = 20_000_000


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

    if not MIN_PBKDF2_ROUNDS <= rounds <= MAX_PBKDF2_ROUNDS:
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


def session_version(password_hash: str) -> str:
    """会话版本号：口令摘要的短哈希。

    令牌里带上它，取用户时再和数据库里的当前摘要比一次。口令一改（用户自己改、
    管理员重置）版本号就变，此前签发的所有令牌立刻失效 —— 无状态令牌本来
    没法撤销，这是能做到「改密码即踢下线」的最小代价。

    只存摘要的哈希、不存摘要本身：HMAC 已经保证令牌不能被伪造，这里再放一层，
    万一令牌被读到也不会顺带泄露口令摘要的结构。
    """
    if not password_hash:
        return ""
    return hashlib.sha256(f"session-v1:{password_hash}".encode()).hexdigest()[:16]


def create_session_token(user_id: int, username: str, role: str, password_hash: str = "") -> str:
    """签发会话令牌（无状态，服务端不落库）。"""
    payload = {
        "uid": user_id,
        "u": username,
        "r": role,
        "ver": session_version(password_hash),
        "exp": int(time.time()) + config.SESSION_TTL_SECONDS,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = _b64url_encode(raw)
    return f"{body}.{_sign(raw)}"


def parse_session_token(token: str | None) -> dict | None:
    """校验签名与有效期并解出会话令牌，失败返回 None。

    这里只做「签名对不对、过没过期」的检查；令牌里的会话版本号要等取到用户
    记录之后再比（见 api/deps.py），因为那需要数据库。
    """
    if not token or token.count(".") != 1:
        return None

    body, signature = token.split(".", 1)
    # HTTP 头按 latin-1 解码，Cookie 里塞进高位字节就会变成非 ASCII 字符串，
    # 而 hmac.compare_digest 对非 ASCII 直接抛 TypeError。先挡掉，别让它变成 500。
    if not signature.isascii():
        return None
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

    if not isinstance(payload, dict):
        return None
    try:
        expired = int(payload.get("exp", 0)) < time.time()
    except (ValueError, TypeError):
        return None
    if expired:
        return None
    return payload


def token_version_matches(payload: dict, password_hash: str) -> bool:
    """令牌里的会话版本号是否与当前口令摘要一致。"""
    return hmac.compare_digest(
        str(payload.get("ver", "")), session_version(password_hash)
    )


def generate_password(length: int = 12) -> str:
    """生成随机初始口令。"""
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))
