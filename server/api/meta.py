"""健康检查与运行期信息。

版本号由两段拼出来：本工具自己的版本 + 各插件回报的「上游模块版本」。
插件通过 `BasePlugin.versions()` 贡献自己的那一段（例如 PickOne 的模块版本），
所以这里不需要认识任何一个具体工具。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

from .. import __version__, config
from .deps import CurrentUser, Registry, Repo

router = APIRouter(tags=["meta"])

# 从 OBot-ACM 源码里读核心版本号的正则（所有插件共用）
_CORE_VERSION_RE = re.compile(r'core_version\s*=\s*"([^"]+)"')


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


def bot_versions(registry: Registry) -> dict[str, str | None]:
    """读 OBot-ACM 自己的版本号与 commit，读不到就返回 None（前端显示 unknown）。

    刻意不去 import Bot 的模块（会拉起一大堆重依赖），只在源码里找常量；
    各插件维护的那个模块版本由插件自己解析，这里只负责合并。
    版本号形如 v5.0.0-10b5ce3，后缀是 OBot-ACM 当前 HEAD 的短哈希。
    """
    root = config.ACM_ROOT_DIR

    core = _CORE_VERSION_RE.search(_read_text(root / "src" / "core" / "constants.py"))
    sha = _head_short_hash(root)

    core_version = core.group(1) if core else None
    if core_version and sha:
        core_version = f"{core_version}-{sha}"

    return {
        "obot": core_version,
        "obot_base": core.group(1) if core else None,
        "commit": sha,
        **registry.versions(),
    }


def _public_versions(registry: Registry) -> dict[str, str | None]:
    """公开给未登录访客的版本信息：只有版本号，没有 commit。

    页面上的版本标签用得上，而 commit 短哈希等于把「所维护仓库的确切代码版本」
    告诉任何访客 —— 那是漏洞探测的现成输入，没必要公开。
    """
    data = bot_versions(registry)
    data.pop("commit", None)
    return {"obot_ep": __version__, **data}


@router.get("/health")
def health() -> dict:
    """无需登录，供探活使用。

    刻意不带 lib_dir 之类的路径：探活接口是公开的，磁盘布局不该出现在这里。
    """
    return {"ok": True, "service": "obot-ep"}


@router.get("/meta/versions")
def versions(registry: Registry) -> dict:
    """版本号：本工具 + 所维护的 OBot-ACM 及其各模块。

    无需登录（页面底部要显示），所以只给版本号，不给 commit（见 _public_versions）。
    """
    return _public_versions(registry)


@router.get("/meta/info")
def info(repo: Repo, registry: Registry, user: CurrentUser) -> dict:
    counts = repo.count_by_status()
    return {
        "user": user.to_dict(),
        "plugins": registry.manifests(),
        "allow_register": config.ALLOW_REGISTER,
        "submission_counts": counts,
        "roles": ["user", "admin"],
        # 登录用户可以看到完整版本信息（含 commit）
        "versions": {"obot_ep": __version__, **bot_versions(registry)},
    }
