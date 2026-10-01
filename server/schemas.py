"""框架级请求/响应模型（认证、账号、审核流程）。

具体工具（插件）的提交内容模型放在 `plugins/<slug>/schemas.py`。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=32)


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


class ReviewRequest(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=200)


class ReviewBatchRequest(BaseModel):
    """批量审核。ids 限制条数，避免一次请求把整个队列塞进来。"""

    ids: list[int] = Field(min_length=1, max_length=200)
    approve: bool
    comment: str = Field(default="", max_length=200)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=8, max_length=256)
    display_name: str = Field(default="", max_length=32)
    role: str = Field(default="user", pattern="^(user|admin)$")


class UserUpdateRequest(BaseModel):
    is_active: bool | None = None
    role: str | None = Field(default=None, pattern="^(user|admin)$")
    password: str | None = Field(default=None, min_length=8, max_length=256)


class ApiResponse(BaseModel):
    ok: bool = True
    data: Any = None
    message: str = ""
