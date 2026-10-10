"""框架级管理路由：审核队列与审核动作、账号管理、审计日志。

这里只碰「提交单」这一层数据结构，不碰任何具体工具的数据文件 —— 所以它对
所有插件通用，新增工具不需要在这里加任何东西。提交单用 `plugin` 参数过滤。

真正写盘（一键应用 / 冲突裁定 / 数据体检）属于「这个工具的数据长什么样」，
由插件在 `/api/plugins/<slug>/admin/` 下自己提供，见 plugins/*/api/admin.py。
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, HTTPException, Query, status

from ..repository import (
    ROLE_ADMIN,
    STATUS_APPROVED,
    STATUS_CONFLICT,
    STATUS_PENDING,
    ConflictError,
    Repository,
)
from ..schemas import (
    ReviewBatchRequest,
    ReviewRequest,
    UserCreateRequest,
    UserUpdateRequest,
)
from .deps import AdminUser, Registry, Repo

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/queue")
def review_queue(
    repo: Repo,
    admin: AdminUser,
    plugin: str = Query(default="", max_length=64, description="只看某个工具的提交单"),
    status_filter: str = Query(
        default="pending",
        alias="status",
        pattern="^(pending|approved|conflict|rejected|applied|all)$",
    ),
    img_key: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1, le=1_000_000),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """待审核 / 待应用 / 冲突 / 已处理队列。"""
    kwargs: dict = {}
    if status_filter != "all":
        kwargs["status"] = status_filter
    items, total = repo.list_submissions(
        plugin=plugin or None,
        img_key=img_key or None,
        limit=page_size,
        offset=(page - 1) * page_size,
        **kwargs,
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [item.to_dict() for item in items],
        "counts": repo.count_by_status(plugin or None),
    }


@router.post("/review/batch")
def review_batch(
        payload: ReviewBatchRequest,
        repo: Repo,
        admin: AdminUser,
) -> dict:
    """批量审核：批准 / 驳回一批提交单。"""
    succeeded: list[int] = []
    failed: list[dict] = []
    for submission_id in payload.ids:
        try:
            repo.review_submission(
                submission_id,
                approve=payload.approve,
                reviewer_id=admin.id,
                comment=payload.comment,
            )
            succeeded.append(submission_id)
        except KeyError:
            failed.append({"id": submission_id, "reason": "不存在"})
        except Exception as error:
            failed.append({"id": submission_id, "reason": str(error)})

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="review_batch",
        detail=f"批量{'通过' if payload.approve else '驳回'} {len(succeeded)} 条，失败 {len(failed)} 条",
        is_admin=True,
    )
    return {"succeeded": succeeded, "failed": failed}


@router.post("/review/{submission_id}")
def review(
    submission_id: int,
    payload: ReviewRequest,
    repo: Repo,
    admin: AdminUser,
) -> dict:
    """审核（批准 / 驳回）。批准只是排队，真正落盘要再点「一键应用」。"""
    submission = repo.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在")

    try:
        updated = repo.review_submission(
            submission_id,
            approve=payload.approve,
            reviewer_id=admin.id,
            comment=payload.comment,
        )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在") from error
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="review_approved" if payload.approve else "review_rejected",
        detail=f"提交单 #{submission_id}（{submission.type_label} @ {submission.img_key}）"
        + (f"，备注：{payload.comment}" if payload.comment else ""),
        is_admin=True,
    )
    return {"submission": updated.to_dict()}


@router.post("/unreview/{submission_id}")
def unreview(submission_id: int, repo: Repo, admin: AdminUser) -> dict:
    """撤回审核：把「已通过待下发」的提交退回「待审核」。

    审核通过后、下发之前管理员改主意（审错了、想再等等、想和别的改动一起发），
    这里可以把它放回待审核队列重新审。
    """
    submission = repo.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在")

    try:
        updated = repo.unreview_submission(submission_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在") from error
    except ConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="review_revoked",
        detail=f"撤回审核 #{submission_id}（{submission.type_label} @ {submission.img_key}），退回待审核",
        is_admin=True,
    )
    return {"submission": updated.to_dict()}


@router.get("/logs")
def logs(
    repo: Repo,
    admin: AdminUser,
    page: int = Query(default=1, ge=1, le=1_000_000),
    page_size: int = Query(default=50, ge=1, le=200),
) -> dict:
    items, total = repo.list_logs(limit=page_size, offset=(page - 1) * page_size)
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.get("/users")
def list_users(repo: Repo, admin: AdminUser) -> dict:
    counts = repo.open_submission_counts()
    users = repo.list_users()
    return {
        "users": [
            {**item.to_dict(), "open_submissions": counts.get(item.id, 0)} for item in users
        ],
        "total_admins": sum(1 for item in users if item.role == ROLE_ADMIN and item.is_active),
    }


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreateRequest, repo: Repo, admin: AdminUser) -> dict:
    try:
        user = repo.create_user(
            payload.username,
            payload.password,
            display_name=payload.display_name,
            role=payload.role,
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="create_user",
        detail=f"创建账号 {user.username}（{user.role}）",
        is_admin=True,
    )
    return {"user": user.to_dict()}


@router.patch("/users/{user_id}")
def update_user(
    user_id: int, payload: UserUpdateRequest, repo: Repo, admin: AdminUser
) -> dict:
    target = repo.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")

    changes: list[str] = []

    if payload.role is not None and payload.role != target.role:
        if target.id == admin.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色"
            )
        if target.role == ROLE_ADMIN and repo.count_admins() <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="至少要保留一个管理员"
            )
        repo.set_user_role(user_id, payload.role)
        changes.append(f"角色 -> {payload.role}")

    if payload.is_active is not None and payload.is_active != target.is_active:
        if target.id == admin.id and not payload.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="不能停用自己的账号"
            )
        if (
            target.role == ROLE_ADMIN
            and target.is_active
            and not payload.is_active
            and repo.count_admins() <= 1
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="至少要保留一个可用的管理员"
            )
        repo.set_user_active(user_id, payload.is_active)
        changes.append("启用" if payload.is_active else "停用")

    if payload.password:
        repo.change_password(user_id, payload.password)
        changes.append("重置密码")

    if not changes:
        return {"user": target.to_dict(), "changed": []}

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="update_user",
        detail=f"更新账号 {target.username}：{'，'.join(changes)}",
        is_admin=True,
    )
    updated = repo.get_user(user_id)
    assert updated is not None
    return {"user": updated.to_dict(), "changed": changes}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, repo: Repo, admin: AdminUser) -> dict:
    target = repo.get_user(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账号不存在")
    if target.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除自己的账号")
    if target.role == ROLE_ADMIN and repo.count_admins() <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="至少要保留一个管理员"
        )

    # 有提交记录的账号删不掉（审核历史还引用着它）。与其让它以 500 的形式
    # 崩在 SQLite 的外键上，不如明确告诉管理员改用什么操作。
    deps = repo.user_dependency_counts(user_id)
    blocking = sum(deps.values())
    if blocking:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"该账号有 {blocking} 条提交记录（作者或审核人），无法直接删除。"
                "若要收回权限，请改为「停用账号」。"
            ),
        )

    try:
        repo.delete_user(user_id)
    except sqlite3.IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该账号仍被其它记录引用，请改为「停用账号」",
        ) from error

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="delete_user",
        detail=f"删除账号 {target.username}",
        is_admin=True,
    )
    return {"ok": True}


@router.get("/overview")
def overview(repo: Repo, registry: Registry, admin: AdminUser) -> dict:
    """管理台首页需要的全部计数（与具体工具无关）。

    插件自己的「数据目录在不在」由 `GET /api/plugins` 的 health 字段给。
    """
    _, pending_total = repo.list_submissions(status=STATUS_PENDING, limit=1)
    _, approved_total = repo.list_submissions(status=STATUS_APPROVED, limit=1)
    counts = repo.count_by_status()
    return {
        "submission_counts": counts,
        "pending_total": pending_total,
        "approved_total": approved_total,
        "conflict_total": counts[STATUS_CONFLICT],
        # 分工具的待办数。导航角标的含义是「**这个工具**的审核台还有几件事」，
        # 拿上面那份全站数贴上去会让每个工具显示同一个数字（也就等于没意义）。
        "plugin_counts": {
            plugin.slug: _plugin_waiting(repo, plugin.slug) for plugin in registry
        },
        "user_total": repo.count_users(),
        "admin_total": repo.count_admins(),
    }


def _plugin_waiting(repo: Repository, slug: str) -> dict[str, int]:
    """某个工具自己的待办：待审核 + 冲突待裁定（与全站那份同一个口径）。"""
    counts = repo.count_by_status(slug)
    return {
        "pending": counts[STATUS_PENDING],
        "conflict": counts[STATUS_CONFLICT],
    }
