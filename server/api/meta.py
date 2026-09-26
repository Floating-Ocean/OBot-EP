"""健康检查与运行期信息。"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

from .. import config
from .deps import CurrentUser, Repo, Store

router = APIRouter(tags=["meta"])

# 从 OBot-ACM 源码里读版本号的正则
_CORE_VERSION_RE = re.compile(r'core_version\s*=\s*"([^"]+)"')
_MODULE_VERSION_RE = re.compile(r'name="Pick-One",\s*version="([^"]+)"')


def _read_text(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _head_short_hash(root) -> str | None:
    """读 OBot-ACM 的 HEAD 短哈希。

    直接读 .git 文件，不调 git 命令：一是快，二是不依赖 PATH 里有没有 git，
    三是 worktree / 子模块下 .git 可能是文件而不是目录，两种情况都处理。
    """
    override = config.ACM_VERSION_SUFFIX
    if override:
        return override

    git = root / ".git"
    if git.is_file():
        # worktree: .git 文件里写着 "gitdir: <path>"
        text = _read_text(git).strip()
        if not text.lower().startswith("gitdir:"):
            return None
        git = Path(text.split(":", 1)[1].strip())

    head = _read_text(git / "HEAD").strip()
    if not head:
        return None

    if head.startswith("ref:"):
        ref = head.split(":", 1)[1].strip()
        sha = _read_text(git / ref).strip()
        if not sha:
            # 可能被打包进 packed-refs
            for line in _read_text(git / "packed-refs").splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    sha = parts[0]
                    break
    else:
        sha = head

    sha = sha.strip()
    return sha[:7] if len(sha) >= 7 and all(c in "0123456789abcdef" for c in sha[:7].lower()) else None


def bot_versions() -> dict[str, str | None]:
    """读 OBot-ACM 自己的版本号与 commit，读不到就返回 None（前端显示 unknown）。

    刻意不去 import Bot 的模块（会拉起一大堆重依赖），只在源码里找两个常量。
    版本号形如 v5.0.0-10b5ce3，后缀是 OBot-ACM 当前 HEAD 的短哈希。
    """
    root = config.ACM_ROOT_DIR

    core = _CORE_VERSION_RE.search(_read_text(root / "src" / "core" / "constants.py"))
    module = _MODULE_VERSION_RE.search(_read_text(root / "src" / "module" / "stuff" / "pick_one.py"))
    sha = _head_short_hash(root)

    core_version = core.group(1) if core else None
    if core_version and sha:
        core_version = f"{core_version}-{sha}"

    return {
        "obot": core_version,
        "obot_base": core.group(1) if core else None,
        "pickone": module.group(1) if module else None,
        "commit": sha,
    }


@router.get("/health")
def health() -> dict:
    """无需登录，供探活使用。"""
    return {"ok": True, "service": "obot-ep", "lib_dir": str(config.PICK_ONE_DIR)}


@router.get("/meta/versions")
def versions() -> dict:
    """版本号：本工具 + 所维护的 OBot-ACM。无需登录，登录页也能显示。"""
    return {"obot_ep": "0.1.0", **bot_versions()}


@router.get("/meta/info")
def info(repo: Repo, store: Store, user: CurrentUser) -> dict:
    counts = repo.count_by_status()
    return {
        "user": user.to_dict(),
        "lib_dir": str(store.lib_dir),
        "lib_available": store.lib_dir.is_dir(),
        "allow_register": config.ALLOW_REGISTER,
        "submission_counts": counts,
        "roles": ["user", "admin"],
        "versions": {"obot_ep": "0.1.0", **bot_versions()},
    }
