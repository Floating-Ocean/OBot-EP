"""认证与账号相关路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from .. import config
from ..repository import ROLE_ADMIN, User
from ..schemas import ChangePasswordRequest, LoginRequest, RegisterRequest
from ..security import create_session_token, verify_password
from .deps import AdminUser, CurrentUser, Repo

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    token = create_session_token(user.id, user.username, user.role)
    response.set_cookie(
        key=config.SESSION_COOKIE,
        value=token,
        max_age=config.SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(payload: LoginRequest, response: Response, repo: Repo) -> dict:
    user = repo.authenticate(payload.username, payload.password)
    if user is None:
        repo.add_log(
            actor_id=None,
            username=payload.username.strip(),
            action="login_failed",
            detail="用户名或密码错误",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    _set_session_cookie(response, user)
    repo.add_log(actor_id=user.id, username=user.username, action="login", detail="登录成功")
    return {"user": user.to_dict()}


@router.post("/logout")
def logout(response: Response, repo: Repo, user: CurrentUser) -> dict:
    response.delete_cookie(config.SESSION_COOKIE, path="/")
    repo.add_log(actor_id=user.id, username=user.username, action="logout", detail="登出")
    return {"ok": True}


@router.get("/me")
def me(user: CurrentUser) -> dict:
    return {"user": user.to_dict()}


@router.get("/config")
def auth_config(repo: Repo) -> dict:
    """登录页需要知道是否允许自助注册、是否还没初始化。"""
    return {
        "allow_register": config.ALLOW_REGISTER,
        "needs_bootstrap": repo.count_users() == 0,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response, repo: Repo) -> dict:
    if not config.ALLOW_REGISTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员已关闭自助注册，请联系管理员开通账号",
        )
    try:
        user = repo.create_user(
            payload.username, payload.password, display_name=payload.display_name
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    _set_session_cookie(response, user)
    repo.add_log(actor_id=user.id, username=user.username, action="register", detail="注册账号")
    return {"user": user.to_dict()}


@router.post("/password")
def change_password(
    payload: ChangePasswordRequest, repo: Repo, user: CurrentUser
) -> dict:
    found = repo.get_user_with_hash(user.username)
    if found is None or not verify_password(payload.old_password, found[1]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")

    repo.change_password(user.id, payload.new_password)
    repo.add_log(actor_id=user.id, username=user.username, action="change_password", detail="修改密码")
    return {"ok": True}


@router.get("/users")
def list_users(admin: AdminUser, repo: Repo) -> dict:
    """管理员查看账号列表，附带待处理提交数。"""
    counts = repo.open_submission_counts()
    users = repo.list_users()
    return {
        "users": [
            {**item.to_dict(), "open_submissions": counts.get(item.id, 0)} for item in users
        ],
        "total_admins": sum(1 for item in users if item.role == ROLE_ADMIN and item.is_active),
    }
