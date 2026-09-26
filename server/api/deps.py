"""共享依赖：取当前登录用户、管理员校验、错误响应。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from .. import config
from ..repository import ROLE_ADMIN, Repository, User
from ..security import parse_session_token
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
    """从会话 Cookie 解出当前用户；未登录一律 401（全站需登录）。"""
    token = request.cookies.get(config.SESSION_COOKIE)
    payload = parse_session_token(token)
    if not payload:
        raise _UNAUTHORIZED

    user = repo.get_user(int(payload.get("uid", 0)))
    if user is None or not user.is_active:
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
