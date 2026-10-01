"""@@NAME@@ 用户侧路由：浏览数据 + 发起提交。

**审核流程不用自己实现**：`/api/admin/queue`、`/api/admin/review/*` 是框架提供的，
对任何工具通用。这里只需要把改动写成一条「提交单」，并把 plugin 标成自己。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from server.api.deps import CurrentUser, Repo

from .. import config
from ..schemas import TextSubmitRequest
from ..types import TYPE_TEXT
from .deps import Store

router = APIRouter(tags=["@@SLUG@@"])


@router.get("/items")
def list_items(store: Store, _user: CurrentUser) -> dict:
    """列出所有条目（跟着磁盘原值走，在途改动不在这里混进来）。"""
    items = store.list_items()
    return {
        "total": len(items),
        "missing_text": sum(1 for item in items if item.needs_text),
        "items": [item.to_dict() for item in items],
    }


@router.get("/items/{key}")
def get_item(key: str, store: Store, _user: CurrentUser) -> dict:
    return {"item": store.item_or_404(key).to_dict()}


@router.get("/submissions")
def list_submissions(
    repo: Repo,
    user: CurrentUser,
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    limit: int = Query(default=100, ge=1, le=200),
) -> dict:
    """列提交单。普通用户只看得到自己的，管理员可以看全部。"""
    author_id = None
    if scope == "mine" or not user.is_admin:
        author_id = user.id
    rows, total = repo.list_submissions(plugin=config.SLUG, author_id=author_id, limit=limit)
    return {"total": total, "items": [row.to_dict() for row in rows]}


@router.post("/submissions", status_code=status.HTTP_201_CREATED)
def create_submission(
    payload: TextSubmitRequest,
    repo: Repo,
    store: Store,
    user: CurrentUser,
) -> dict:
    """提交一条改动。真正写盘要等管理员在审核台点「一键下发」。"""
    item = store.item_or_404(payload.key)
    text = payload.text.strip()
    if text == item.text:
        # 提交回当前值等于撤回修改，而不是一条新提交 —— 让它进来只会污染队列
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="提交内容与当前值相同，无需修改"
        )

    submission, created = repo.upsert_submission(
        plugin=config.SLUG,
        type=TYPE_TEXT,
        # 框架的提交单模型：img_key 是「这条改动挂在哪个资源上」，
        # target 用来区分同一个资源下的不同字段（这里只有文本，所以留空）。
        img_key=payload.key,
        target="",
        submitted_value=text,
        note=payload.note.strip(),
        author_id=user.id,
        # 记下提交时看到的值：应用时用它检测「期间被别人改过」的冲突
        base_value=item.text,
    )
    repo.add_log(
        actor_id=user.id,
        username=user.username,
        action="submit_text",
        detail=f"{'新建' if created else '更新'} {TYPE_TEXT} @ {payload.key}",
    )
    return {"submission": submission.to_dict()}


@router.delete("/submissions/{submission_id}")
def withdraw(submission_id: int, repo: Repo, user: CurrentUser) -> dict:
    """撤回自己待审核的提交。"""
    submission = repo.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在")
    if submission.author_id != user.id and not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只能撤回自己的提交")

    try:
        repo.withdraw_submission(submission_id)
    except KeyError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="提交单不存在"
        ) from error
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    repo.add_log(
        actor_id=user.id,
        username=user.username,
        action="withdraw_submission",
        detail=f"撤回提交单 #{submission_id}",
    )
    return {"ok": True}
