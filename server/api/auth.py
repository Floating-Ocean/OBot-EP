"""认证与账号相关路由。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from .. import config
from ..ratelimit import RateLimiter
from ..repository import ROLE_ADMIN, User
from ..schemas import ChangePasswordRequest, LoginRequest, RegisterRequest
from ..security import create_session_token, verify_password
from .deps import AdminUser, CurrentUser, Repo

logger = logging.getLogger("obot_ep")

router = APIRouter(prefix="/auth", tags=["auth"])

# 按「客户端地址」和「用户名」各限一份：地址那份挡住单机爆破，用户名那份挡住
# 换 IP 撞同一个账号。两者都按来源区分，所以还额外有一份全站上限兜底
# （见下方 _global_auth），防止分散来源的并发请求把 PBKDF2 的 CPU 吃满。
_login_by_ip = RateLimiter(config.LOGIN_MAX_PER_WINDOW, config.LOGIN_WINDOW_SECONDS)
_login_by_user = RateLimiter(config.LOGIN_MAX_PER_WINDOW, config.LOGIN_WINDOW_SECONDS)
_register_by_ip = RateLimiter(config.REGISTER_MAX_PER_WINDOW, config.REGISTER_WINDOW_SECONDS)
_password_by_user = RateLimiter(config.PASSWORD_MAX_PER_WINDOW, config.PASSWORD_WINDOW_SECONDS)

# 全站共享的认证预算：登录 / 注册 / 改密都从这里扣
_global_auth = RateLimiter(
    config.GLOBAL_AUTH_MAX_PER_WINDOW, config.GLOBAL_AUTH_WINDOW_SECONDS
)
_GLOBAL_KEY = "auth"

# 客户端地址不可信时要退回一个固定桶，但不能因此完全不限速
_UNKNOWN_CLIENT = "unknown"


def _global_budget_exhausted() -> int:
    """超出全站认证预算时返回建议等待秒数，否则返回 0。"""
    return _global_auth.retry_after(_GLOBAL_KEY)


def _forwarded_client(request: Request) -> str:
    """从代理头里取真实客户端地址。

    仅在 OBOT_EP_TRUST_PROXY=1 时调用，并且假设代理会**覆写**这两个头
    （nginx 的 proxy_set_header / Caddy 的默认行为都是覆写）。X-Forwarded-For
    是追加式的，所以从右往左取第一个不在 TRUSTED_PROXY_IPS 里的地址：客户端
    自己伪造的部分只会出现在左边，取右边拿到的才是代理写进去的那一跳。
    """
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        hops = [item.strip() for item in forwarded.split(",") if item.strip()]
        for hop in reversed(hops):
            if hop not in config.TRUSTED_PROXY_IPS:
                return hop
        if hops:
            return hops[0]
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return ""


def _client_key(request: Request) -> str:
    """发起请求的地址。

    默认只取 TCP 连接本身 —— 转发头是客户端可控的，信它等于没限速。
    只有在明确配置了 OBOT_EP_TRUST_PROXY（服务只被自己的代理访问）时才读代理头，
    否则反代后面所有请求会共用一个配额。
    """
    if config.TRUST_PROXY:
        forwarded = _forwarded_client(request)
        if forwarded:
            return forwarded
    client = request.client
    return client.host if client and client.host else _UNKNOWN_CLIENT


def _too_many(retry_after: int, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(retry_after)},
    )


def _set_session_cookie(response: Response, user: User, password_hash: str) -> None:
    token = create_session_token(user.id, user.username, user.role, password_hash)
    response.set_cookie(
        value=token,
        max_age=config.SESSION_TTL_SECONDS,
        **config.session_cookie_kwargs(),
    )


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response, repo: Repo) -> dict:
    username = payload.username.strip()
    ip_key = f"ip:{_client_key(request)}"
    user_key = f"user:{username.casefold()}"

    # 先看限速再算 PBKDF2：否则被限速的请求照样能把 CPU 吃掉。
    #
    # 注意这里「地址超限」和「账号超限」分别判断，不是二选一：
    # 地址桶挡的是「一台机器撞很多账号」，账号桶挡的是「很多机器撞一个账号」。
    # 两个桶都只在失败时累加、成功时清空，所以正常人不会被自己的手误拖累。
    for limiter, key in ((_login_by_ip, ip_key), (_login_by_user, user_key)):
        wait = limiter.retry_after(key)
        if wait:
            logger.warning("login rate limited (%s)", key.split(":", 1)[0])
            raise _too_many(wait, "登录尝试过于频繁，请稍后再试")

    wait = _global_budget_exhausted()
    if wait:
        logger.warning("auth budget exhausted")
        raise _too_many(wait, "服务繁忙，请稍后再试")

    _global_auth.record(_GLOBAL_KEY)

    user = repo.authenticate(username, payload.password)
    if user is None:
        # 只有失败才计入限速：成功的登录不该占用爆破预算，否则十来个正常用户
        # 就能把同一个出口 IP（家用 NAT、公司网关、反代）锁在门外。
        _login_by_ip.record(ip_key)
        _login_by_user.record(user_key)
        repo.add_log(
            actor_id=None,
            username=username,
            action="login_failed",
            detail="用户名或密码错误",
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    # 登录成功清掉这个账号和这个地址的失败计数
    _login_by_ip.clear(ip_key)
    _login_by_user.clear(user_key)

    found = repo.get_user_and_hash(user.id)
    if found is None:  # pragma: no cover - 刚认证成功又消失，只可能是并发删除
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )
    _set_session_cookie(response, user, found[1])
    repo.add_log(actor_id=user.id, username=user.username, action="login", detail="登录成功")
    return {"user": user.to_dict()}


@router.post("/logout")
def logout(response: Response, repo: Repo, user: CurrentUser) -> dict:
    response.delete_cookie(
        config.SESSION_COOKIE, path="/", httponly=True, samesite="lax",
        secure=config.COOKIE_SECURE,
    )
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
def register(payload: RegisterRequest, request: Request, response: Response, repo: Repo) -> dict:
    if not config.ALLOW_REGISTER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="管理员已关闭自助注册，请联系管理员开通账号",
        )

    register_key = f"ip:{_client_key(request)}"
    # 注册同样要算 PBKDF2，而且会真的写库，所以未通过校验就不要再往下走。
    # 被限速的请求只写进程日志：审计表是磁盘写入，让 429 也落库等于给攻击者
    # 留了一条「比正常请求更便宜」的写盘通道。
    wait = _register_by_ip.retry_after(register_key) or _global_budget_exhausted()
    if wait:
        logger.warning("register rate limited (%s)", register_key.split(":", 1)[0])
        raise _too_many(wait, "注册请求过于频繁，请稍后再试")

    try:
        user = repo.create_user(
            payload.username, payload.password, display_name=payload.display_name
        )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    _global_auth.record(_GLOBAL_KEY)
    _register_by_ip.record(register_key)

    found = repo.get_user_and_hash(user.id)
    if found is None:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="账号创建失败"
        )
    _set_session_cookie(response, user, found[1])
    repo.add_log(actor_id=user.id, username=user.username, action="register", detail="注册账号")
    return {"user": user.to_dict()}


@router.post("/password")
def change_password(
    payload: ChangePasswordRequest, response: Response, repo: Repo, user: CurrentUser
) -> dict:
    found = repo.get_user_with_hash(user.username)
    if found is None or not verify_password(payload.old_password, found[1]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码不正确")

    limiter_key = f"user:{user.id}"
    wait = _password_by_user.retry_after(limiter_key) or _global_budget_exhausted()
    if wait:
        raise _too_many(wait, "改密过于频繁，请稍后再试")

    repo.change_password(user.id, payload.new_password)
    _global_auth.record(_GLOBAL_KEY)
    _password_by_user.record(limiter_key)

    # 改密后口令摘要变了，旧令牌全部失效（这正是我们要的「改密码踢下线」）。
    # 当前这个浏览器重新签一张，免得用户改完密码自己也被踢出去。
    refreshed = repo.get_user_and_hash(user.id)
    if refreshed is not None:
        _set_session_cookie(response, refreshed[0], refreshed[1])

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
