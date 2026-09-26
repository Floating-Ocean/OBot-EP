"""请求/响应模型。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .store import (
    MAX_ALIAS_LENGTH,
    MAX_ALIASES,
    MAX_CATEGORY_ID_LENGTH,
    MAX_COMMENT_LENGTH,
    MAX_COMMENTS_PER_IMAGE,
    MAX_LIKES_PER_REQUEST,
    MAX_OCR_TEXT_LENGTH,
)


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


class OcrSubmitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    ocr_text: str = Field(max_length=MAX_OCR_TEXT_LENGTH)
    note: str = Field(default="", max_length=200)


class LikesSubmitRequest(BaseModel):
    """likes_delta 是这次「加多少赞」，不是这张图的目标赞数。

    限的是单次能加的数量（对应 Bot 一条 /点赞 加 1 个），磁盘上的总数不封顶，
    所以本来就有几十个赞的图照样能继续加。
    """

    name: str = Field(min_length=1, max_length=64)
    likes_delta: int = Field(ge=1, le=MAX_LIKES_PER_REQUEST)
    note: str = Field(default="", max_length=200)


class ImageBatchRequest(BaseModel):
    """一张图片的多个字段一起提交（编辑表单）。

    只处理明确给出的字段；没传的字段不动，所以「清空 OCR」用空字符串表示即可。
    """

    name: str = Field(min_length=1, max_length=64)
    ocr_text: str | None = Field(default=None, max_length=MAX_OCR_TEXT_LENGTH)
    likes_delta: int | None = Field(default=None, ge=1, le=MAX_LIKES_PER_REQUEST)
    comments: list[str] | None = Field(default=None, max_length=MAX_COMMENTS_PER_IMAGE)
    note: str = Field(default="", max_length=200)


class CommentsSubmitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    comments: list[str] = Field(max_length=MAX_COMMENTS_PER_IMAGE)
    note: str = Field(default="", max_length=200)

    def cleaned(self) -> list[str]:
        out: list[str] = []
        for comment in self.comments:
            text = " ".join(comment.split())
            if not text:
                continue
            if len(text) > MAX_COMMENT_LENGTH:
                raise ValueError(f"单条评论过长（上限 {MAX_COMMENT_LENGTH} 字）")
            out.append(text)
        return out


class CategorySubmitRequest(BaseModel):
    category_id: str = Field(min_length=1, max_length=MAX_CATEGORY_ID_LENGTH)
    keys: list[str] = Field(min_length=1, max_length=MAX_ALIASES)
    note: str = Field(default="", max_length=200)


class CategoryCreateRequest(BaseModel):
    category_id: str = Field(default="", max_length=MAX_CATEGORY_ID_LENGTH)
    keys: list[str] = Field(default_factory=list, max_length=MAX_ALIASES)
    note: str = Field(default="", max_length=200)


class ReviewRequest(BaseModel):
    approve: bool
    comment: str = Field(default="", max_length=200)


class ConflictResolveRequest(BaseModel):
    """冲突裁定：保留提交的新值（写入），或丢弃提交（保持磁盘现状）。"""

    keep_new: bool


class ApplyRequest(BaseModel):
    dry_run: bool = False


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
