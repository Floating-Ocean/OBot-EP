"""@@NAME@@ 管理侧路由（挂载于 `/api/plugins/@@SLUG@@/admin`）。

这里放的全是「只有这个工具才知道怎么做」的动作：把审核通过的提交写回数据文件。
通用的那部分（审核队列、审核动作、账号、日志）在框架的 `/api/admin/*` 下，不要重复实现。

`/apply`、`/apply/preview`、`/overview` 三个路径是**约定**：框架的通用审核台
（web/src/views/admin/PluginReviewView.vue）按这三个路径调用，请保持它们存在。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from server.api.deps import AdminUser, Repo
from server.errors import StoreError, ValidationError
from server.repository import STATUS_CONFLICT

from .. import config
from .deps import Store

router = APIRouter(prefix="/admin", tags=["@@SLUG@@-admin"])


@router.get("/overview")
def overview(repo: Repo, store: Store, admin: AdminUser) -> dict:
    """审核台首页需要的计数与数据目录状态。"""
    counts = repo.count_by_status(config.SLUG)
    return {
        "submission_counts": counts,
        "conflict_total": counts[STATUS_CONFLICT],
        "lib_dir": str(getattr(store, "data_dir", "")),
        # 数据目录读不到时，审核台会提示「只能审核、下发会失败」
        "lib_available": True,
    }


@router.get("/apply/preview")
def apply_preview(repo: Repo, store: Store, admin: AdminUser) -> dict:
    """下发前的 dry-run：只列出将要写入的内容，不碰磁盘。"""
    submissions = repo.list_approved_submissions(config.SLUG)
    return {
        "submissions": len(submissions),
        "changes": [
            {"key": item.img_key, "target": item.target, "value": item.submitted_value}
            for item in submissions
        ],
        "conflicts": [],
    }


@router.post("/apply")
def apply_changes(repo: Repo, store: Store, admin: AdminUser) -> dict:
    """一键下发：把 approved 的提交写回数据文件。

    TODO(@@SLUG@@): 这里刻意**没有**做冲突检测。如果数据文件也会被别人（Bot、别的
    脚本）改动，下发前应该把 `submission.base_value` 和磁盘现值比一比，不一致就挂成
    `conflict` 状态让管理员裁定，而不是直接覆盖。完整做法见
    `plugins/pickone/changes.py` 与 `plugins/pickone/api/admin.py`。
    """
    submissions = repo.list_approved_submissions(config.SLUG)
    if not submissions:
        return {"applied": 0, "submissions": 0}

    data = store.load()
    for submission in submissions:
        data.setdefault(submission.img_key, {})["text"] = submission.submitted_value

    try:
        store.save(data)
    except (StoreError, ValidationError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except OSError:
        # 底层异常信息里带着服务端的绝对路径，不往响应里放
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="写盘失败（权限或磁盘问题），请查看服务端日志",
        ) from None

    for submission in submissions:
        repo.mark_applied(submission.id, submission.submitted_value)

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="apply_changes",
        detail=f"应用 {len(submissions)} 条提交",
        is_admin=True,
    )
    return {"applied": len(submissions), "submissions": len(submissions)}
