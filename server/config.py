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
SESSION_SECRET = os.environ.get("OBOT_EP_SECRET") or secrets.token_urlsafe(32)
SESSION_TTL_SECONDS = int(os.environ.get("OBOT_EP_SESSION_TTL", 30 * 24 * 3600))
SESSION_COOKIE = "obot_ep_session"

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

# 生成缩略图时动画帧的最大数量（GIF 动图只取前几帧，避免解压炸弹）
THUMB_MAX_FRAMES = 4
THUMB_MAX_SIDE = 320


def ensure_dirs() -> None:
    """确保运行时目录存在。"""
    for path in (DATA_DIR, THUMB_DIR):
        path.mkdir(parents=True, exist_ok=True)
