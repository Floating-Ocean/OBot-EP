"""@@NAME@@ 的提交类型。

框架只存 `type` 字符串；这些常量以及「哪个类型叫什么名字」是这个工具自己的词汇表，
通过 `register_submission_types()` 告知框架。
"""

from __future__ import annotations

# TODO(@@SLUG@@): 换成这个工具真正要改的字段。一个字段一个类型。
TYPE_TEXT = "text"

SUBMISSION_TYPES = (TYPE_TEXT,)

TYPE_LABELS = {
    TYPE_TEXT: "文本内容",
}
