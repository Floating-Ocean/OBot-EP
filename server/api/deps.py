"""共享依赖：取当前登录用户、管理员校验、错误响应。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from .. import config
from ..repository import ROLE_ADMIN, Repository, User
from ..security import parse_session_token, token_version_matches
from ..store import PickOneStore

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="请先登录",
)


def get_repo(request: Request) -> Repository:
    return request.app.state.repo


def get_store(request: Request) -> PickOneStore:
    return request.app.state.store


def get_current_user(
    request: Request,
    repo: Annotated[Repository, Depends(get_repo)],
) -> User:
    """从会话 Cookie 解出当前用户；未登录一律 401（全站需登录）。

    角色和启用状态都以数据库为准，不信令牌里的副本；令牌里的会话版本号还要
    和当前口令摘要对上，这样改密码 / 被停用之后旧令牌立刻作废。
    """
    token = request.cookies.get(config.SESSION_COOKIE)
    payload = parse_session_token(token)
    if not payload:
        raise _UNAUTHORIZED

    try:
        user_id = int(payload.get("uid", 0))
    except (TypeError, ValueError):
        raise _UNAUTHORIZED from None

    found = repo.get_user_and_hash(user_id)
    if found is None:
        raise _UNAUTHORIZED
    user, password_hash = found
    if not user.is_active:
        raise _UNAUTHORIZED
    if not token_version_matches(payload, password_hash):
        raise _UNAUTHORIZED
    return user


def get_admin_user(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
AdminUser = Annotated[User, Depends(get_admin_user)]
Repo = Annotated[Repository, Depends(get_repo)]
Store = Annotated[PickOneStore, Depends(get_store)]
