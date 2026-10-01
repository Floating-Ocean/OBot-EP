"""@@NAME@@ 数据访问层。

TODO(@@SLUG@@): 换成真正读写上游数据的逻辑。现在这份是一个**能跑通的最小实现**：
一个 JSON 文件存 `{"<key>": {"text": "..."}}`，够用来验证插件接线是否正确。
改成什么都行，但请保留两件事：

  1. 写盘用「临时文件 + os.replace」，别让并发请求读到半截文件（Bot 也是这么写的）；
  2. 可预期的错误用 `server.errors` 里的类型抛 —— 核心已经给它们装好了 400/404 处理器。
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.errors import NotFoundError, ValidationError

from . import config

RECORDS_FILENAME = "records.json"


@dataclass
class Item:
    key: str
    text: str

    @property
    def needs_text(self) -> bool:
        return not self.text.strip()

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "text": self.text, "needs_text": self.needs_text}


class ItemStore:
    """@@NAME@@ 的数据读写入口。"""

    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = Path(data_dir or config.DATA_DIR)

    @property
    def records_path(self) -> Path:
        return self.data_dir / RECORDS_FILENAME

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            raw = json.loads(self.records_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise ValidationError(f"读取数据文件失败: {error}") from error
        if not isinstance(raw, dict):
            raise ValidationError("数据文件格式不对：顶层应该是对象")
        return {
            str(key): value if isinstance(value, dict) else {}
            for key, value in raw.items()
        }

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        """原子写：临时文件 + os.replace，避免读到半截 JSON。"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = self.records_path.with_name(
            f".{self.records_path.name}.{os.getpid()}.{threading.get_ident()}."
            f"{secrets.token_hex(4)}.tmp"
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=4)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.records_path)
        finally:
            with contextlib.suppress(OSError):
                tmp_path.unlink()

    def list_items(self) -> list[Item]:
        return [self._to_item(key, value) for key, value in sorted(self.load().items())]

    def item_or_404(self, key: str) -> Item:
        data = self.load()
        if key not in data:
            raise NotFoundError(f"条目不存在: {key}")
        return self._to_item(key, data[key])

    @staticmethod
    def _to_item(key: str, value: dict[str, Any]) -> Item:
        return Item(key=key, text=str(value.get("text") or ""))
