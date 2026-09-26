"""SQLite 持久层：账号、会话无关的提交单与审计日志。

提交单模型刻意把「审核」和「应用」拆成两个状态：

    pending   --审核通过-->  approved  --一键应用-->  applied
       \\--审核驳回--> rejected

也就是说审核只是把改动排出队列，真正落到 OBot-ACM 的 JSON 要管理员再点一次
「一键应用」。这样批量改动可以攒在一起，也便于应用前再看一眼 diff。
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import config
from .security import hash_password, verify_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    display_name  TEXT    NOT NULL DEFAULT '',
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'user',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    REAL    NOT NULL,
    last_login_at REAL
);

CREATE TABLE IF NOT EXISTS submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    type            TEXT    NOT NULL,
    img_key         TEXT    NOT NULL,
    target          TEXT    NOT NULL DEFAULT '',
    base_value      TEXT,
    submitted_value TEXT    NOT NULL,
    note            TEXT    NOT NULL DEFAULT '',
    status          TEXT    NOT NULL DEFAULT 'pending',
    author_id       INTEGER NOT NULL REFERENCES users(id),
    reviewer_id     INTEGER REFERENCES users(id),
    review_comment  TEXT    NOT NULL DEFAULT '',
    created_at      REAL    NOT NULL,
    reviewed_at     REAL,
    applied_at      REAL,
    applied_value   TEXT,
    -- 冲突挂起时记录三方对比（提交时原值 / 磁盘现值 / 提交新值）与判定理由
    conflict_detail TEXT,
    conflict_at     REAL
);

-- 同一用户对同一目标只允许一条「在途」提交（待审 / 已通过 / 冲突待裁定），
-- 用户反复改同一个字段会覆盖这条记录，而不是把队列刷爆。
-- 注意 author_id 必须在索引里：否则 A 提交后 B 就被挡住，没法同时给同一张图提修改。
CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_pending
    ON submissions(type, img_key, target, author_id)
    WHERE status IN ('pending', 'approved', 'conflict');

CREATE INDEX IF NOT EXISTS idx_submissions_status ON submissions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_submissions_author ON submissions(author_id, created_at DESC);

CREATE TABLE IF NOT EXISTS audit_logs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id   INTEGER REFERENCES users(id),
    action     TEXT    NOT NULL,
    detail     TEXT    NOT NULL DEFAULT '',
    created_at REAL    NOT NULL,
    is_admin   INTEGER NOT NULL DEFAULT 0,
    username   TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
"""

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_APPLIED = "applied"
# 审核通过后、应用时发现磁盘上的原值已被改动：挂起来等管理员裁定
STATUS_CONFLICT = "conflict"

# 还占着「同一目标只有一条在途提交」名额的状态
OPEN_STATUSES = (STATUS_PENDING, STATUS_APPROVED)
# 已经走完流程、不再占用名额的状态
CLOSED_STATUSES = (STATUS_REJECTED, STATUS_APPLIED)
ALL_STATUSES = (STATUS_PENDING, STATUS_APPROVED, STATUS_CONFLICT, STATUS_REJECTED, STATUS_APPLIED)

TYPE_OCR_TEXT = "ocr_text"
TYPE_LIKES = "likes"
TYPE_COMMENTS = "comments"
TYPE_CATEGORY = "category"
TYPE_CATEGORY_CREATE = "category_create"

SUBMISSION_TYPES = (
    TYPE_OCR_TEXT,
    TYPE_LIKES,
    TYPE_COMMENTS,
    TYPE_CATEGORY,
    TYPE_CATEGORY_CREATE,
)

# 落在 parser.json 里的提交类型（相对的是写 config.json 的类别类提交）
IMAGE_TYPES = (TYPE_OCR_TEXT, TYPE_LIKES, TYPE_COMMENTS)

TYPE_LABELS = {
    TYPE_OCR_TEXT: "图片描述",
    TYPE_LIKES: "点赞",
    TYPE_COMMENTS: "评论",
    TYPE_CATEGORY: "类别信息",
    TYPE_CATEGORY_CREATE: "新增类别",
}

ROLE_USER = "user"
ROLE_ADMIN = "admin"


@dataclass
class User:
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: float
    last_login_at: float | None

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def label(self) -> str:
        return self.display_name or self.username

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "label": self.label,
            "role": self.role,
            "is_admin": self.is_admin,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_login_at": self.last_login_at,
        }


@dataclass
class Submission:
    id: int
    type: str
    img_key: str
    target: str
    base_value: Any
    submitted_value: Any
    note: str
    status: str
    author_id: int
    author_name: str
    reviewer_id: int | None
    reviewer_name: str | None
    review_comment: str
    created_at: float
    reviewed_at: float | None
    applied_at: float | None
    applied_value: Any
    conflict_detail: dict[str, Any] | None = None
    conflict_at: float | None = None

    @property
    def type_label(self) -> str:
        return TYPE_LABELS.get(self.type, self.type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "type_label": self.type_label,
            "img_key": self.img_key,
            "target": self.target,
            "base_value": self.base_value,
            "submitted_value": self.submitted_value,
            "note": self.note,
            "status": self.status,
            "author_id": self.author_id,
            "author_name": self.author_name,
            "reviewer_id": self.reviewer_id,
            "reviewer_name": self.reviewer_name,
            "review_comment": self.review_comment,
            "created_at": self.created_at,
            "reviewed_at": self.reviewed_at,
            "applied_at": self.applied_at,
            "applied_value": self.applied_value,
            "conflict_detail": self.conflict_detail,
            "conflict_at": self.conflict_at,
        }


class ConflictError(Exception):
    """并发或状态冲突。"""


class Repository:
    """线程安全的 SQLite 封装（uvicorn 多线程下共用一个连接 + 互斥锁）。"""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path or config.DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ---------- 内部小工具 ----------

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cursor

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, tuple(params)).fetchall())

    def _query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    # ---------- 用户 ----------

    def count_admins(self) -> int:
        row = self._query_one(
            "SELECT COUNT(*) AS n FROM users WHERE role = ? AND is_active = 1", (ROLE_ADMIN,)
        )
        return int(row["n"]) if row else 0

    def count_users(self) -> int:
        row = self._query_one("SELECT COUNT(*) AS n FROM users")
        return int(row["n"]) if row else 0

    @staticmethod
    def _row_to_user(row: sqlite3.Row) -> User:
        return User(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"] or ""),
            role=str(row["role"]),
            is_active=bool(row["is_active"]),
            created_at=float(row["created_at"]),
            last_login_at=float(row["last_login_at"]) if row["last_login_at"] else None,
        )

    def get_user(self, user_id: int) -> User | None:
        row = self._query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        return self._row_to_user(row) if row is not None else None

    def get_user_by_username(self, username: str) -> sqlite3.Row | None:
        return self._query_one(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE", (username.strip(),)
        )

    def find_user(self, username: str) -> User | None:
        """按用户名取 User（大小写不敏感）。管理 CLI 与接口层用这个。"""
        row = self.get_user_by_username(username)
        return self._row_to_user(row) if row is not None else None

    def get_user_with_hash(self, username: str) -> tuple[User, str] | None:
        row = self.get_user_by_username(username)
        if row is None:
            return None
        return self._row_to_user(row), str(row["password_hash"])

    def create_user(
        self,
        username: str,
        password: str,
        *,
        display_name: str = "",
        role: str = ROLE_USER,
    ) -> User:
        username = username.strip()
        if not username:
            raise ValueError("用户名不能为空")
        if len(username) > 32:
            raise ValueError("用户名过长（上限 32 字符）")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", username):
            raise ValueError("用户名只能包含字母、数字、下划线、短横线和点")
        if len(password) < 8:
            raise ValueError("密码至少 8 位")
        if role not in (ROLE_USER, ROLE_ADMIN):
            raise ValueError(f"未知角色: {role}")
        if self.get_user_by_username(username) is not None:
            raise ValueError(f"用户名已存在: {username}")

        cursor = self._execute(
            "INSERT INTO users (username, display_name, password_hash, role, is_active, created_at)"
            " VALUES (?, ?, ?, ?, 1, ?)",
            (username, display_name.strip(), hash_password(password), role, time.time()),
        )
        user = self.get_user(int(cursor.lastrowid))
        assert user is not None
        return user

    def authenticate(self, username: str, password: str) -> User | None:
        found = self.get_user_with_hash(username)
        if found is None:
            return None
        user, password_hash = found
        if not user.is_active or not verify_password(password, password_hash):
            return None
        self._execute("UPDATE users SET last_login_at = ? WHERE id = ?", (time.time(), user.id))
        return self.get_user(user.id)

    def list_users(self) -> list[User]:
        rows = self._query("SELECT * FROM users ORDER BY id")
        return [self._row_to_user(row) for row in rows]

    def change_password(self, user_id: int, new_password: str) -> None:
        if len(new_password) < 8:
            raise ValueError("密码至少 8 位")
        self._execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )

    def set_user_active(self, user_id: int, is_active: bool) -> None:
        self._execute("UPDATE users SET is_active = ? WHERE id = ?", (1 if is_active else 0, user_id))

    def set_user_role(self, user_id: int, role: str) -> None:
        if role not in (ROLE_USER, ROLE_ADMIN):
            raise ValueError(f"未知角色: {role}")
        self._execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))

    def delete_user(self, user_id: int) -> None:
        self._execute("DELETE FROM users WHERE id = ?", (user_id,))

    def open_submission_counts(self) -> dict[int, int]:
        """每个作者还待处理的提交数（pending + approved）。"""
        rows = self._query(
            "SELECT author_id, COUNT(*) AS n FROM submissions"
            " WHERE status IN (?, ?) GROUP BY author_id",
            OPEN_STATUSES,
        )
        return {int(row["author_id"]): int(row["n"]) for row in rows}

    # ---------- 提交单 ----------

    @staticmethod
    def _row_to_submission(row: sqlite3.Row) -> Submission:
        return Submission(
            id=int(row["id"]),
            type=str(row["type"]),
            img_key=str(row["img_key"]),
            target=str(row["target"] or ""),
            base_value=_loads(row["base_value"]),
            submitted_value=_loads(row["submitted_value"]),
            note=str(row["note"] or ""),
            status=str(row["status"]),
            author_id=int(row["author_id"]),
            author_name=str(row["author_name"] or row["author_username"] or ""),
            reviewer_id=int(row["reviewer_id"]) if row["reviewer_id"] else None,
            reviewer_name=str(row["reviewer_name"] or "") if row["reviewer_id"] else None,
            review_comment=str(row["review_comment"] or ""),
            created_at=float(row["created_at"]),
            reviewed_at=float(row["reviewed_at"]) if row["reviewed_at"] else None,
            applied_at=float(row["applied_at"]) if row["applied_at"] else None,
            applied_value=_loads(row["applied_value"]),
            conflict_detail=_loads(row["conflict_detail"]),
            conflict_at=float(row["conflict_at"]) if row["conflict_at"] else None,
        )

    _SUBMISSION_SELECT = """
        SELECT s.*,
               author.username                                AS author_username,
               COALESCE(NULLIF(author.display_name, ''), author.username) AS author_name,
               COALESCE(NULLIF(reviewer.display_name, ''), reviewer.username) AS reviewer_name
        FROM submissions s
        JOIN users author   ON author.id = s.author_id
        LEFT JOIN users reviewer ON reviewer.id = s.reviewer_id
    """

    def upsert_submission(
        self,
        *,
        type: str,
        img_key: str,
        target: str,
        submitted_value: Any,
        note: str,
        author_id: int,
        base_value: Any = None,
    ) -> tuple[Submission, bool]:
        """新建或覆盖同一目标的待处理提交单，返回 (提交单, 是否新建)。

        同一 (type, img_key, target) 只会有一条 pending/approved 记录，
        因此用户反复修改同一字段不会把审核队列刷爆；每次操作仍会写审计日志。
        """
        if type not in SUBMISSION_TYPES:
            raise ValueError(f"未知提交类型: {type}")

        payload = _dumps(submitted_value)
        now = time.time()

        with self._lock:
            # conflict 也算「在途」：用户重新提交同一目标时应该覆盖掉冲突单
            existing = self._conn.execute(
                "SELECT * FROM submissions WHERE type = ? AND img_key = ? AND target = ?"
                " AND author_id = ? AND status IN (?, ?, ?)",
                (type, img_key, target, author_id, *OPEN_STATUSES, STATUS_CONFLICT),
            ).fetchone()

            if existing is not None:
                self._conn.execute(
                    "UPDATE submissions SET submitted_value = ?, note = ?, author_id = ?,"
                    " status = ?, created_at = ?, base_value = COALESCE(base_value, ?),"
                    " conflict_detail = NULL, conflict_at = NULL"
                    " WHERE id = ?",
                    (payload, note, author_id, STATUS_PENDING, now,
                     _dumps(base_value), int(existing["id"])),
                )
                self._conn.commit()
                row = self._fetch_submission(int(existing["id"]))
                assert row is not None
                return row, False

            cursor = self._conn.execute(
                "INSERT INTO submissions (type, img_key, target, base_value, submitted_value,"
                " note, status, author_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (type, img_key, target, _dumps(base_value), payload, note,
                 STATUS_PENDING, author_id, now),
            )
            self._conn.commit()

        row = self._fetch_submission(int(cursor.lastrowid))
        assert row is not None
        return row, True

    def _fetch_submission(self, submission_id: int) -> Submission | None:
        row = self._query_one(self._SUBMISSION_SELECT + " WHERE s.id = ?", (submission_id,))
        return self._row_to_submission(row) if row is not None else None

    def get_submission(self, submission_id: int) -> Submission | None:
        return self._fetch_submission(submission_id)

    def list_submissions(
        self,
        *,
        status: str | None = None,
        statuses: Iterable[str] | None = None,
        author_id: int | None = None,
        img_key: str | None = None,
        type: str | None = None,
        types: Iterable[str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Submission], int]:
        where: list[str] = []
        params: list[Any] = []
        if status:
            where.append("s.status = ?")
            params.append(status)
        elif statuses:
            values = list(statuses)
            if values:
                where.append(f"s.status IN ({', '.join('?' for _ in values)})")
                params.extend(values)
        if author_id is not None:
            where.append("s.author_id = ?")
            params.append(author_id)
        if img_key:
            where.append("s.img_key = ?")
            params.append(img_key)
        if type:
            where.append("s.type = ?")
            params.append(type)
        elif types:
            values = [item for item in types]
            if values:
                where.append(f"s.type IN ({', '.join('?' for _ in values)})")
                params.extend(values)

        clause = f" WHERE {' AND '.join(where)}" if where else ""
        total_row = self._query_one(
            "SELECT COUNT(*) AS n FROM submissions s" + clause, params
        )
        total = int(total_row["n"]) if total_row else 0

        page_size = 100000 if limit is None else max(1, min(limit, 200))
        rows = self._query(
            self._SUBMISSION_SELECT + clause + " ORDER BY s.created_at DESC LIMIT ? OFFSET ?",
            [*params, page_size, max(0, offset)],
        )
        return [self._row_to_submission(row) for row in rows], total

    def count_by_status(self) -> dict[str, int]:
        rows = self._query("SELECT status, COUNT(*) AS n FROM submissions GROUP BY status")
        counts = {status: 0 for status in ALL_STATUSES}
        for row in rows:
            counts[str(row["status"])] = int(row["n"])
        return counts

    def count_by_status_for_author(self, author_id: int) -> dict[str, int]:
        """某个用户自己的提交按状态计数。

        「我的提交」页面的统计卡必须用这个，否则管理员看到的是全站数字，
        跟普通用户看到的没区别。
        """
        rows = self._query(
            "SELECT status, COUNT(*) AS n FROM submissions WHERE author_id = ? GROUP BY status",
            (author_id,),
        )
        counts = {status: 0 for status in ALL_STATUSES}
        for row in rows:
            counts[str(row["status"])] = int(row["n"])
        return counts

    def list_open_submissions_for_author(self, author_id: int) -> list[Submission]:
        rows = self._query(
            self._SUBMISSION_SELECT
            + " WHERE s.author_id = ? AND s.status IN (?, ?) ORDER BY s.created_at DESC",
            (author_id, *OPEN_STATUSES),
        )
        return [self._row_to_submission(row) for row in rows]

    def list_approved_submissions(self) -> list[Submission]:
        """待应用的提交单，按 id 升序保证可预期地覆盖。"""
        rows = self._query(
            self._SUBMISSION_SELECT
            + " WHERE s.status = ? ORDER BY s.id ASC",
            (STATUS_APPROVED,),
        )
        return [self._row_to_submission(row) for row in rows]

    def open_submissions_for_target(
        self, type: str, img_key: str, target: str, author_id: int | None = None
    ) -> list[Submission]:
        """某个目标上还没落盘的提交。给了 author_id 就只看这个人的。"""
        sql = (
            self._SUBMISSION_SELECT
            + " WHERE s.type = ? AND s.img_key = ? AND s.target = ?"
            " AND s.status IN (?, ?)"
        )
        params: list[Any] = [type, img_key, target, *OPEN_STATUSES]
        if author_id is not None:
            sql += " AND s.author_id = ?"
            params.append(author_id)
        return [self._row_to_submission(row) for row in self._query(sql + " ORDER BY s.id ASC", params)]

    def review_submission(
        self, submission_id: int, *, approve: bool, reviewer_id: int, comment: str = ""
    ) -> Submission:
        row = self._query_one("SELECT * FROM submissions WHERE id = ?", (submission_id,))
        if row is None:
            raise KeyError(submission_id)

        current_status = str(row["status"])
        if current_status == STATUS_CONFLICT:
            raise ConflictError("该提交存在冲突，请在「冲突处理」中裁定")
        if current_status != STATUS_PENDING:
            raise ConflictError(f"提交单当前状态为 {current_status}，无法再次审核")

        self._execute(
            "UPDATE submissions SET status = ?, reviewer_id = ?, review_comment = ?,"
            " reviewed_at = ? WHERE id = ?",
            (STATUS_APPROVED if approve else STATUS_REJECTED, reviewer_id,
             comment.strip(), time.time(), submission_id),
        )
        result = self._fetch_submission(submission_id)
        assert result is not None
        return result

    def unreview_submission(self, submission_id: int) -> Submission:
        """撤回审核：把「已通过待下发」的提交退回「待审核」。

        只有还没写盘的 approved 能退 —— applied 已经落到数据文件里了，
        conflict 要走冲突裁定，两者都不该从这里改状态。
        """
        row = self._query_one("SELECT status FROM submissions WHERE id = ?", (submission_id,))
        if row is None:
            raise KeyError(submission_id)

        current_status = str(row["status"])
        if current_status != STATUS_APPROVED:
            raise ConflictError("只有「已通过待下发」的提交可以撤回审核")

        self._execute(
            "UPDATE submissions SET status = ?, reviewer_id = NULL, review_comment = '',"
            " reviewed_at = NULL WHERE id = ?",
            (STATUS_PENDING, submission_id),
        )
        result = self._fetch_submission(submission_id)
        assert result is not None
        return result

    def resolve_submission_conflict(
        self, submission_id: int, *, keep_new: bool, reviewer_id: int
    ) -> Submission:
        row = self._query_one("SELECT status FROM submissions WHERE id = ?", (submission_id,))
        if row is None:
            raise KeyError(submission_id)
        if str(row["status"]) != STATUS_CONFLICT:
            raise ConflictError("该提交当前不在冲突状态")

        self.resolve_conflict(submission_id, keep_new=keep_new, reviewer_id=reviewer_id)
        result = self._fetch_submission(submission_id)
        assert result is not None
        return result

    def mark_applied(self, submission_id: int, applied_value: Any) -> None:
        self._execute(
            "UPDATE submissions SET status = ?, applied_at = ?, applied_value = ?,"
            " conflict_detail = NULL, conflict_at = NULL WHERE id = ?",
            (STATUS_APPLIED, time.time(), _dumps(applied_value), submission_id),
        )

    def mark_conflict(self, submission_id: int, detail: dict[str, Any]) -> None:
        """应用时发现原值被改动：把提交单挂到 conflict 状态等待裁定。"""
        self._execute(
            "UPDATE submissions SET status = ?, conflict_detail = ?, conflict_at = ?"
            " WHERE id = ? AND status = ?",
            (STATUS_CONFLICT, _dumps(detail), time.time(), submission_id, STATUS_APPROVED),
        )

    def resolve_conflict(self, submission_id: int, *, keep_new: bool, reviewer_id: int) -> None:
        """裁定冲突。

        keep_new=True  -> 改回 approved，下一次应用会覆盖磁盘上的当前值
        keep_new=False -> 丢弃这条提交（rejected），磁盘保持现状
        """
        now = time.time()
        if keep_new:
            self._execute(
                "UPDATE submissions SET status = ?, reviewer_id = ?, reviewed_at = ?,"
                " conflict_detail = NULL, conflict_at = NULL, review_comment = ?"
                " WHERE id = ? AND status = ?",
                (
                    STATUS_APPROVED,
                    reviewer_id,
                    now,
                    "冲突裁定：保留提交的新值，应用时覆盖磁盘当前值",
                    submission_id,
                    STATUS_CONFLICT,
                ),
            )
        else:
            self._execute(
                "UPDATE submissions SET status = ?, reviewer_id = ?, reviewed_at = ?,"
                " conflict_detail = NULL, conflict_at = NULL, review_comment = ?"
                " WHERE id = ? AND status = ?",
                (
                    STATUS_REJECTED,
                    reviewer_id,
                    now,
                    "冲突裁定：丢弃提交，保留磁盘当前值",
                    submission_id,
                    STATUS_CONFLICT,
                ),
            )

    def withdraw_submission(self, submission_id: int) -> None:
        row = self._query_one("SELECT status FROM submissions WHERE id = ?", (submission_id,))
        if row is None:
            raise KeyError(submission_id)
        if str(row["status"]) != STATUS_PENDING:
            raise ConflictError("只有待审核的提交可以撤回")
        self._execute("DELETE FROM submissions WHERE id = ?", (submission_id,))

    def has_open_submission(self, type: str, img_key: str, target: str) -> bool:
        row = self._query_one(
            "SELECT 1 AS x FROM submissions WHERE type = ? AND img_key = ? AND target = ?"
            " AND status IN (?, ?) LIMIT 1",
            (type, img_key, target, *OPEN_STATUSES),
        )
        return row is not None

    # ---------- 审计日志 ----------

    def add_log(
        self,
        *,
        actor_id: int | None,
        username: str,
        action: str,
        detail: str = "",
        is_admin: bool = False,
    ) -> None:
        self._execute(
            "INSERT INTO audit_logs (actor_id, username, action, detail, created_at, is_admin)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (actor_id, username, action, detail, time.time(), 1 if is_admin else 0),
        )

    def list_logs(self, *, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        total_row = self._query_one("SELECT COUNT(*) AS n FROM audit_logs")
        total = int(total_row["n"]) if total_row else 0
        rows = self._query(
            "SELECT * FROM audit_logs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (max(1, min(limit, 500)), max(0, offset)),
        )
        return [
            {
                "id": int(row["id"]),
                "actor_id": row["actor_id"],
                "username": str(row["username"] or ""),
                "action": str(row["action"]),
                "detail": str(row["detail"] or ""),
                "created_at": float(row["created_at"]),
                "is_admin": bool(row["is_admin"]),
            }
            for row in rows
        ], total


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return raw
