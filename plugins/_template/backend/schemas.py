"""@@NAME@@ 的请求模型。

框架只提供认证 / 账号 / 审核流程的模型（`server/schemas.py`）；
「提交什么内容」是这个工具自己的事。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

MAX_TEXT_LENGTH = 512


class TextSubmitRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=MAX_TEXT_LENGTH)
    note: str = Field(default="", max_length=200)
