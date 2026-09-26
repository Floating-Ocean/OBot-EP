"""管理员路由：审核、一键应用、账号管理、审计日志。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from .. import config
from ..changes import apply_approved, build_apply_plan, resolve_conflict
from ..repository import (
    ROLE_ADMIN,
    STATUS_APPROVED,
    STATUS_CONFLICT,
    STATUS_PENDING,
    ConflictError,
    Repository,
)
from ..schemas import ApplyRequest, ConflictResolveRequest, ReviewRequest, UserCreateRequest, UserUpdateRequest
from ..store import StoreError, ValidationError
from .deps import AdminUser, Repo, Store

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/queue")
def review_queue(
    repo: Repo,
    admin: AdminUser,
    status_filter: str = Query(
        default="pending",
        alias="status",
        pattern="^(pending|approved|conflict|rejected|applied|all)$",
    ),
    img_key: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """待审核 / 待应用 / 冲突 / 已处理队列。"""
    kwargs: dict = {}
    if status_filter != "all":
        kwargs["status"] = status_filter
    items, total = repo.list_submissions(
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
        "counts": repo.count_by_status(),
    }


@router.post("/review/batch")
def review_batch(
        payload: dict,
        repo: Repo,
        admin: AdminUser,
) -> dict:
    """批量审核。body: {"ids": [...], "approve": true, "comment": ""}"""
    ids = payload.get("ids") or []
    approve = bool(payload.get("approve"))
    comment = str(payload.get("comment") or "")[:200]

    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择要审核的提交")

    succeeded: list[int] = []
    failed: list[dict] = []
    for raw_id in ids[:200]:
        try:
            submission_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        try:
            repo.review_submission(
                submission_id, approve=approve, reviewer_id=admin.id, comment=comment
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
        detail=f"批量{'通过' if approve else '驳回'} {len(succeeded)} 条，失败 {len(failed)} 条",
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


@router.get("/apply/preview")
def apply_preview(repo: Repo, store: Store, admin: AdminUser) -> dict:
    """应用前的 dry-run：列出将要写入的内容与冲突。"""
    return _build_apply_preview(repo, store)


def _build_apply_preview(repo: Repository, store) -> dict:
    submissions = repo.list_approved_submissions()
    if not submissions:
        return {
            "submissions": 0,
            "image_changes": [],
            "category_entries": [],
            "conflicts": [],
            "new_keys": [],
            "lib_dir": str(store.lib_dir),
        }

    plan = build_apply_plan(store, submissions)

    image_changes = [
        {
            "img_key": img_key,
            "count": len(items),
            "items": [
                {"name": item["name"], "field": item["field"], "value": item["value"]}
                for item in items
            ],
        }
        for img_key, items in plan.image_changes.items()
    ]

    return {
        "submissions": len(plan.applied_ids),
        "image_changes": image_changes,
        "category_entries": [
            {"img_key": img_key, "entry": entry}
            for img_key, entry in plan.category_entries.items()
        ],
        "new_keys": plan.new_keys,
        "conflicts": [conflict.to_dict() for conflict in plan.conflicts],
        "lib_dir": str(store.lib_dir),
    }


@router.get("/conflicts")
def list_conflicts(
    repo: Repo,
    admin: AdminUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """列出所有挂起的冲突，附三方对比信息。"""
    items, total = repo.list_submissions(
        status=STATUS_CONFLICT, limit=page_size, offset=(page - 1) * page_size
    )
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [item.to_dict() for item in items],
        "counts": repo.count_by_status(),
    }


@router.post("/conflicts/{submission_id}/resolve")
def resolve(
    submission_id: int,
    payload: ConflictResolveRequest,
    repo: Repo,
    store: Store,
    admin: AdminUser,
) -> dict:
    """裁定冲突：keep_new=true 保留提交新值并立即写入，false 丢弃提交。"""
    from ..changes import ApplyConflictError

    try:
        result = resolve_conflict(
            repo, store, submission_id, keep_new=payload.keep_new, reviewer_id=admin.id
        )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在") from error
    except ApplyConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    except (StoreError, ValidationError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except OSError as error:
        # 英文的底层错误，避免把中文写进可能被开发模式打印的异常里
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写盘失败（权限或磁盘问题）: {error}",
        ) from error

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="resolve_conflict",
        detail=(
            f"冲突裁定 #{submission_id}："
            + ("保留提交新值并已写入" if payload.keep_new else "丢弃提交，保留磁盘现值")
        ),
        is_admin=True,
    )
    return result


@router.post("/apply")
def apply_changes(payload: ApplyRequest, repo: Repo, store: Store, admin: AdminUser) -> dict:
    """一键应用：把已审核的改动写回 OBot-ACM 的 config.json / parser.json。"""
    if payload.dry_run:
        return _build_apply_preview(repo, store)

    if not config.PICK_ONE_DIR.is_dir():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Pick-One 数据目录不存在: {config.PICK_ONE_DIR}",
        )

    try:
        result = apply_approved(repo, store)
    except (StoreError, ValidationError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"写盘失败: {error}",
        ) from error

    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="apply_changes",
        detail=(
            f"应用 {result['submissions']} 条提交：图片字段 {result['applied_images']} 处，"
            f"类别 {result['applied_categories']} 个，冲突 {len(result['conflicts'])} 条"
        ),
        is_admin=True,
    )
    return result


@router.get("/integrity")
def integrity(store: Store, admin: AdminUser) -> dict:
    """数据体检：图片和 parser.json 是否对齐。"""
    return store.check_integrity()


@router.get("/logs")
def logs(
    repo: Repo,
    admin: AdminUser,
    page: int = Query(default=1, ge=1),
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

    repo.delete_user(user_id)
    repo.add_log(
        actor_id=admin.id,
        username=admin.username,
        action="delete_user",
        detail=f"删除账号 {target.username}",
        is_admin=True,
    )
    return {"ok": True}


@router.get("/overview")
def overview(repo: Repo, store: Store, admin: AdminUser) -> dict:
    """管理台首页需要的全部计数。"""
    _, pending_total = repo.list_submissions(status=STATUS_PENDING, limit=1)
    _, approved_total = repo.list_submissions(status=STATUS_APPROVED, limit=1)
    return {
        "submission_counts": repo.count_by_status(),
        "pending_total": pending_total,
        "approved_total": approved_total,
        "user_total": repo.count_users(),
        "admin_total": repo.count_admins(),
        "lib_dir": str(store.lib_dir),
        "lib_available": config.PICK_ONE_DIR.is_dir(),
    }
