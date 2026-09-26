"""与 OBot-ACM 保持一致的 ID 编码，以及缩略图生成。

`md5_to_base62` / `base62_to_md5` 必须与 `src/core/util/tools.py` 完全一致，
否则 Web 端展示的 ID 和 Bot 回复里的 ID 对不上。
"""

from __future__ import annotations

import hashlib
import io
import string
import threading

from PIL import Image

from . import config

_BASE62_CHARSET = string.ascii_letters + string.digits
_CHAR_TO_INDEX = {char: index for index, char in enumerate(_BASE62_CHARSET)}

MD5_LENGTH = 32
GIF_SUFFIX = ".gif"


def md5_to_base62(md5_hash: str) -> str:
    """将 MD5 转换为 Base62 格式, 字符集[a-zA-Z0-9]。"""
    if len(md5_hash) != 32:
        raise ValueError("md5 must be a 32-char hex string")
    num = int(md5_hash, 16)
    if num == 0:
        return _BASE62_CHARSET[0]

    out = ""
    while num > 0:
        num, remainder = divmod(num, 62)
        out = _BASE62_CHARSET[remainder] + out
    return out


def base62_to_md5(base62_str: str) -> str:
    """将 Base62 转换为 MD5, 字符集[a-zA-Z0-9]。"""
    if not base62_str or len(base62_str) > 22:
        raise ValueError("base62 length must be within 1..22")
    invalid = [char for char in base62_str if char not in _CHAR_TO_INDEX]
    if invalid:
        raise ValueError(f"invalid base62 characters: {''.join(invalid)}")

    num = 0
    for char in base62_str:
        num = num * 62 + _CHAR_TO_INDEX[char]
    if num > (1 << 128) - 1:
        raise ValueError("base62 value exceeds the 128-bit md5 range")
    return format(num, "032x")


def is_md5(name: str) -> bool:
    """判断是否为 32 位小写十六进制（图片文件名即其 MD5）。"""
    if len(name) != MD5_LENGTH:
        return False
    return all(char in "0123456789abcdef" for char in name)


def md5_of_bytes(raw: bytes) -> str:
    return hashlib.md5(raw).hexdigest()


def hash_id_of(stem: str) -> str:
    """图片文件名（不含扩展名）-> 展示用 Base62 ID。"""
    return md5_to_base62(stem)


def new_legacy_entry(ocr_text: str, add_time: float) -> dict:
    """按 Bot 的旧版结构构造一条记录，保证写回后 Bot 完全兼容。"""
    return {
        "ocr_text": ocr_text,
        "add_time": add_time,
        "likes": 0,
        "comments": [],
        "pickup_times": 0,
    }


_thumb_lock = threading.Lock()


def make_thumbnail(raw: bytes, max_side: int = config.THUMB_MAX_SIDE) -> bytes:
    """把动图/静图压成一张 WebP 缩略图。"""
    with Image.open(io.BytesIO(raw)) as img:
        frames = []
        try:
            for index in range(min(getattr(img, "n_frames", 1), config.THUMB_MAX_FRAMES)):
                img.seek(index)
                frames.append(img.convert("RGBA").copy())
        except (EOFError, ValueError):
            pass

        if not frames:
            frames = [img.convert("RGBA")]

        first = frames[0]
        # 动图取各帧平均时长，叠成一个静态图，省掉 WebP 动画的兼容麻烦
        if len(frames) > 1:
            width, height = first.size
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            for frame in frames:
                canvas = Image.alpha_composite(canvas, frame)
            first = Image.blend(frames[0], canvas, 0.35)

        first.thumbnail((max_side, max_side), Image.LANCZOS)
        buffer = io.BytesIO()
        first.convert("RGBA").save(buffer, format="WEBP", quality=82, method=4)
        return buffer.getvalue()


def thumbnail_cache_key(path_text: str, mtime_ns: int, size: int) -> str:
    """缩略图缓存文件名，源文件变化时自动失效。"""
    raw = f"{path_text}|{mtime_ns}|{size}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()
