"""运行期配置：数据目录、数据库、密钥等。

所有配置都可以通过环境变量覆盖，默认值面向本机开发。
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

_DEFAULT_ACM_LIB = BASE_DIR.parent / "OBot-ACM" / "lib"
# OBot-ACM 仓库根目录，用来读它自己的版本号
DEFAULT_ACM_ROOT = BASE_DIR.parent / "OBot-ACM"


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(raw).expanduser().resolve() if raw else default


# OBot-ACM 的 lib 目录，Pick-One 数据（config.json / parser.json / *.gif）都在这里
ACM_LIB_DIR = _env_path("OBOT_ACM_LIB_DIR", _DEFAULT_ACM_LIB)

# OBot-ACM 的源码根目录（用来读它的版本号），默认是 lib 的同级
ACM_ROOT_DIR = _env_path("OBOT_ACM_ROOT_DIR", DEFAULT_ACM_ROOT)

# 覆盖 OBot-ACM 版本号后面的 commit 后缀（不放 git 仓库时可以用）
ACM_VERSION_SUFFIX = os.environ.get("OBOT_ACM_VERSION_SUFFIX", "").strip()

# Pick-One 模块目录
PICK_ONE_DIR = _env_path("OBOT_PICK_ONE_DIR", ACM_LIB_DIR / "Pick-One")

# 本地数据库（账号、提交单、审计日志）
DATA_DIR = _env_path("OBOT_EP_DATA_DIR", BASE_DIR / "data")
DB_PATH = _env_path("OBOT_EP_DB_PATH", DATA_DIR / "obot_ep.sqlite3")

# 缩略图缓存目录
THUMB_DIR = _env_path("OBOT_EP_THUMB_DIR", DATA_DIR / "thumbnails")

# 前端构建产物
FRONTEND_DIST = _env_path("OBOT_EP_FRONTEND_DIST", BASE_DIR / "web" / "dist")

# 会话签名密钥；未配置时随机生成（进程重启后所有登录失效）
SESSION_SECRET_FROM_ENV = bool(os.environ.get("OBOT_EP_SECRET"))
SESSION_SECRET = os.environ.get("OBOT_EP_SECRET") or secrets.token_urlsafe(32)
SESSION_TTL_SECONDS = int(os.environ.get("OBOT_EP_SESSION_TTL", 30 * 24 * 3600))
SESSION_COOKIE = "obot_ep_session"
# 只在 HTTPS 下要求浏览器带上会话 Cookie。默认关闭是为了本机 http://127.0.0.1 直接可用；
# 挂到域名 / 反代后面时设 OBOT_EP_COOKIE_SECURE=1，否则 Cookie 会明文过网络。
COOKIE_SECURE = os.environ.get("OBOT_EP_COOKIE_SECURE", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# 首个管理员账号（仅在数据库里没有任何管理员时创建）
DEFAULT_ADMIN_USERNAME = os.environ.get("OBOT_EP_ADMIN_USER", "admin")
# 留空则自动生成随机密码并在启动日志中打印一次
DEFAULT_ADMIN_PASSWORD = os.environ.get("OBOT_EP_ADMIN_PASSWORD", "")

# 是否允许访客自助注册账号（注册后即可提交修改，但仍需管理员审核）
ALLOW_REGISTER = os.environ.get("OBOT_EP_ALLOW_REGISTER", "1").strip().lower() not in (
    "0",
    "false",
    "no",
)

# 额外信任的写请求来源（CSRF 校验用），逗号分隔的完整 origin，例如
# `https://obus.example.com`。默认空：直接部署时 Origin 与 Host 本来就一致。
EXTRA_TRUSTED_ORIGINS = os.environ.get("OBOT_EP_TRUSTED_ORIGINS", "").strip()

# 是否信任反向代理传来的客户端地址（X-Real-IP / X-Forwarded-For）。
# 默认关闭：这两个头客户端可以自己伪造，信任它们等于让限速形同虚设。
# 只有在服务确实只被自己的代理访问（代理会覆写这两个头）时才打开。
TRUST_PROXY = os.environ.get("OBOT_EP_TRUST_PROXY", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# 代理会追加 X-Forwarded-For，所以取最右边的地址即真实来源；若这里列出代理自身
# 的地址，则从右往左跳过它们（逗号分隔）。
TRUSTED_PROXY_IPS = frozenset(
    item.strip()
    for item in os.environ.get("OBOT_EP_TRUSTED_PROXY_IPS", "").split(",")
    if item.strip()
)

# 生成缩略图时动画帧的最大数量（GIF 动图只取前几帧，避免解压炸弹）
THUMB_MAX_FRAMES = 4
THUMB_MAX_SIDE = 320
# 单张图片文件的大小上限（缩略图会整个读进内存）。正常表情包远小于这个数。
THUMB_MAX_FILE_BYTES = int(os.environ.get("OBOT_EP_THUMB_MAX_FILE_BYTES", 16 * 1024 * 1024))
# Pillow 允许解码的最大像素数：超限直接报错而不是把内存吃光。
# 注意上限同时也是内存预算：解码时每帧按 RGBA 展开（4 字节/像素），再叠加
# 合成画布，40M 像素就能让峰值内存上到 GB 级，所以这里刻意压到 12M
# （约 4000x3000，远大于任何真实的聊天表情包）。
THUMB_MAX_PIXELS = int(os.environ.get("OBOT_EP_THUMB_MAX_PIXELS", 12_000_000))

# HTTP 请求体上限（字节）。JSON 接口的正常请求体都只有几 KB，
# 不设限的话一个匿名请求就能用超大 body 把内存吃光。
MAX_REQUEST_BODY_BYTES = int(os.environ.get("OBOT_EP_MAX_BODY_BYTES", 256 * 1024))

# 是否暴露 /docs、/redoc、/openapi.json。
# 默认关闭：这三个接口不需要登录，会把整套接口面（参数、模型、错误结构）
# 交给任何能连上端口的人。本机开发想看文档时设 OBOT_EP_ENABLE_DOCS=1 即可。
ENABLE_DOCS = os.environ.get("OBOT_EP_ENABLE_DOCS", "0").strip().lower() in (
    "1",
    "true",
    "yes",
)

# 进程实际绑定的地址，由启动脚本/入口写入 uvicorn 的那个 --host。
# 应用本身看不到 socket 绑定地址，靠这个值在启动时判断「是不是在对网络提供服务」。
BIND_HOST = os.environ.get("OBOT_EP_BIND_HOST", "").strip()

# ---- 认证接口限速（防在线爆破与批量注册刷 CPU） ----
# 每个窗口内允许的次数；设 0 表示不限制。
LOGIN_MAX_PER_WINDOW = int(os.environ.get("OBOT_EP_LOGIN_MAX", 10))
LOGIN_WINDOW_SECONDS = int(os.environ.get("OBOT_EP_LOGIN_WINDOW", 300))
REGISTER_MAX_PER_WINDOW = int(os.environ.get("OBOT_EP_REGISTER_MAX", 20))
REGISTER_WINDOW_SECONDS = int(os.environ.get("OBOT_EP_REGISTER_WINDOW", 3600))
PASSWORD_MAX_PER_WINDOW = int(os.environ.get("OBOT_EP_PASSWORD_MAX", 10))
PASSWORD_WINDOW_SECONDS = int(os.environ.get("OBOT_EP_PASSWORD_WINDOW", 900))
# 全站上限（不限来源）。按键限速挡不住「换用户名 + 分散来源」的并发爆破：
# 每个请求都要算一次 PBKDF2，几百个并发就能把线程池占满。
# 只有反向代理才会让所有请求共用一个来源地址，所以这条不是多此一举。
GLOBAL_AUTH_MAX_PER_WINDOW = int(os.environ.get("OBOT_EP_AUTH_GLOBAL_MAX", 60))
GLOBAL_AUTH_WINDOW_SECONDS = int(os.environ.get("OBOT_EP_AUTH_GLOBAL_WINDOW", 60))


def ensure_dirs() -> None:
    """确保运行时目录存在。"""
    for path in (DATA_DIR, THUMB_DIR):
        path.mkdir(parents=True, exist_ok=True)


def session_cookie_kwargs() -> dict:
    """会话 Cookie 的公共属性（签发与清除要用同一份）。"""
    return {
        "key": SESSION_COOKIE,
        "path": "/",
        "httponly": True,
        "samesite": "lax",
        "secure": COOKIE_SECURE,
    }
