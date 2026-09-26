"""提交单叠加、冲突检测与一键应用。

浏览接口要给出「磁盘原值 + 审核中的改动」两套信息（原值用于编辑，在途改动只读展示），
审核后的写入需要按目标合并，这两件事都放在这里，路由层只负责鉴权和参数校验。

冲突从哪来：``parser.json`` / ``config.json`` 是 Bot 也在写的文件。
一条提交单在「用户提交」和「管理员应用」之间可能被别人（Bot 的 OCR 任务、
别人的提交）改过。这时直接覆盖就会静默丢掉那次改动，所以流程是：

  1. 应用时逐条比对「提交时看到的原值」与磁盘当前值
  2. 不一致的提交单转成 ``conflict`` 状态挂起，**不写盘**
  3. 管理员在「冲突处理」里看到三方对比（原值 / 磁盘现值 / 提交新值）后裁定：
     保留新值（立即覆盖写入）或丢弃提交（保持磁盘现状）

点赞是增量（提交单里存的是「加多少」），加在磁盘现值上就是正确结果，
所以不存在冲突，也不参与上面的比对。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .hashing import new_legacy_entry
from .repository import (
    OPEN_STATUSES,
    TYPE_CATEGORY,
    TYPE_CATEGORY_CREATE,
    TYPE_COMMENTS,
    TYPE_LIKES,
    TYPE_OCR_TEXT,
    Repository,
    Submission,
)
from .store import Category, ImageStat, PickOneStore

CATEGORY_TYPES = (TYPE_CATEGORY, TYPE_CATEGORY_CREATE)


class ApplyConflictError(Exception):
    """裁定冲突时冲突依然存在（例如裁定瞬间又被改）。"""


@dataclass
class Conflict:
    """一条无法直接应用的提交，以及裁定它需要的全部信息。"""

    submission: Submission
    reason: str
    current_value: Any = None
    base_value: Any = None
    missing: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "submission_id": self.submission.id,
            "type": self.submission.type,
            "type_label": self.submission.type_label,
            "img_key": self.submission.img_key,
            "target": self.submission.target,
            "author_name": self.submission.author_name,
            "reason": self.reason,
            "missing": self.missing,
            # base_value      提交时看到的原值
            # current_value   磁盘现在的值
            # submitted_value 用户提交的新值
            "base_value": self.base_value,
            "current_value": self.current_value,
            "submitted_value": self.submission.submitted_value,
            "note": self.submission.note,
            "detected_at": self.submission.conflict_at,
        }


def field_of(submission: Submission) -> str | None:
    """提交类型 -> parser.json 字段名。"""
    return field_for_type(submission.type)


def field_for_type(submission_type: str) -> str | None:
    """提交类型 -> parser.json 字段名。"""
    if submission_type == TYPE_OCR_TEXT:
        return "ocr_text"
    if submission_type == TYPE_LIKES:
        return "likes"
    if submission_type == TYPE_COMMENTS:
        return "comments"
    return None


def _pending_entry(submission: Submission) -> dict[str, Any]:
    """一条在途改动在浏览接口里的展示形式。"""
    return {
        "submission_id": submission.id,
        "status": submission.status,
        "author_id": submission.author_id,
        "author_name": submission.author_name,
        "created_at": submission.created_at,
        "note": submission.note,
    }


def image_pending_changes(
    submissions: list[Submission],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """把在途提交整理成 {img_key: {image_name: [改动, ...]}}。

    只记录「有哪些审核中的改动」，不把新值叠加到原值上：浏览与编辑看到的
    字段值永远是磁盘原值，别人的在途改动只作为参考信息展示，不能被当成修改起点。
    """
    grouped: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for submission in submissions:
        name = field_of(submission)
        if name is None:
            continue
        grouped.setdefault(submission.img_key, {}).setdefault(submission.target, []).append(
            {
                **_pending_entry(submission),
                "field": name,
                "value": submission.submitted_value,
            }
        )
    return grouped


def load_open_submissions(repo: Repository) -> list[Submission]:
    """取出所有 pending + approved 的提交单（浏览页展示在途改动用）。"""
    collected: list[Submission] = []
    for status in OPEN_STATUSES:
        rows, _ = repo.list_submissions(status=status, limit=200)
        collected.extend(rows)
    return collected


def category_pending_changes(
    submissions: list[Submission],
) -> dict[str, list[dict[str, Any]]]:
    """类别类在途提交折叠成 {img_key: [改动, ...]}（value 形如 {id, keys}）。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for submission in submissions:
        if submission.type not in CATEGORY_TYPES:
            continue
        value = submission.submitted_value if isinstance(submission.submitted_value, dict) else {}
        grouped.setdefault(submission.img_key, []).append(
            {
                **_pending_entry(submission),
                "value": {"id": value.get("id"), "keys": value.get("keys")},
                "is_new": submission.type == TYPE_CATEGORY_CREATE,
            }
        )
    return grouped


def _sorted_pending(pending: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return sorted(pending or [], key=lambda item: item["submission_id"])


def _with_mine(pending: list[dict[str, Any]], viewer_id: int | None) -> list[dict[str, Any]]:
    return [{**item, "mine": item["author_id"] == viewer_id} for item in pending]


def effective_image(
    stat: ImageStat, pending: list[dict[str, Any]] | None = None, *, viewer_id: int | None = None
) -> dict[str, Any]:
    """把图片信息与在途改动一起交给前端。

    字段值始终是磁盘原值，在途改动单独放在 pending_changes 里 —— 前端据此
    既能看到别人审核中的内容，又只能基于原版本提交自己的修改。
    """
    pending = _sorted_pending(pending)
    return {
        "name": stat.name,
        "md5": stat.md5,
        "hash_id": stat.hash_id,
        "ocr_text": stat.ocr_text,
        "add_time": stat.add_time,
        "likes": stat.likes,
        "comments": list(stat.comments),
        "pickup_times": stat.pickup_times,
        "legacy": stat.legacy,
        "has_pending_change": bool(pending),
        "pending_fields": sorted({item["field"] for item in pending}),
        "pending_changes": _with_mine(pending, viewer_id),
    }


def effective_category(
    category: Category,
    pending: list[dict[str, Any]] | None = None,
    *,
    viewer_id: int | None = None,
) -> dict[str, Any]:
    """类别展示信息：磁盘上的原值 + 在途改动（同样不叠加）。"""
    pending = _sorted_pending(pending)
    return {
        "img_key": category.img_key,
        "id": category.id,
        "keys": list(category.keys),
        "image_count": category.image_count,
        "missing_ocr": 0,
        "pending_fields": ["id", "keys"] if pending else [],
        "pending_changes": _with_mine(pending, viewer_id),
        "is_pending_new": any(item["is_new"] for item in pending),
    }



def pending_category_drafts(repo: Repository) -> list[dict[str, Any]]:
    """列出只在提交单里存在、尚待处理的新类别。"""
    drafts: list[dict[str, Any]] = []
    rows, _ = repo.list_submissions(types=CATEGORY_TYPES, limit=200)
    for submission in rows:
        if submission.type != TYPE_CATEGORY_CREATE:
            continue
        value = submission.submitted_value if isinstance(submission.submitted_value, dict) else {}
        drafts.append(
            {
                "img_key": submission.img_key,
                "id": value.get("id") or submission.img_key,
                "keys": value.get("keys") or [],
                "status": submission.status,
                "submission_id": submission.id,
                "author_name": submission.author_name,
            }
        )
    return drafts


# ------------------------------------------------------------------ 冲突检测


def _same(left: Any, right: Any) -> bool:
    """比较两个字段值是否等价。列表按集合比，避免顺序变化误报冲突。"""
    if isinstance(left, list) or isinstance(right, list):
        return sorted(str(item) for item in (left or [])) == sorted(
            str(item) for item in (right or [])
        )
    return left == right


def image_conflict(store: PickOneStore, submission: Submission) -> Conflict | None:
    """检查一条图片字段提交在磁盘上是否已经被改动过。"""
    name = field_of(submission)
    if name is None:
        return None

    try:
        stat = store.get_image_stat(submission.img_key, submission.target)
    except Exception:
        return Conflict(
            submission=submission,
            reason="图片已不存在或不再属于该类别",
            base_value=submission.base_value,
            current_value=None,
            missing=True,
        )

    current = list(stat.comments) if name == "comments" else getattr(stat, name)

    # 点赞是增量：不管磁盘现值被谁加过，把提交的增量加到现值上都是正确结果
    if submission.type == TYPE_LIKES:
        return None

    if submission.base_value is None or _same(submission.base_value, current):
        return None

    return Conflict(
        submission=submission,
        reason="提交后原值已被改动（可能是 Bot 的 OCR 任务，或另一个人的提交）",
        base_value=submission.base_value,
        current_value=current,
    )


def category_conflict(store: PickOneStore, submission: Submission) -> Conflict | None:
    """检查类别提交：新增撞名、已有类别被删或被改、别名被占用。"""
    existing = store.load_categories().get(submission.img_key)
    value = submission.submitted_value if isinstance(submission.submitted_value, dict) else {}

    if submission.type == TYPE_CATEGORY_CREATE:
        if existing is not None:
            return Conflict(
                submission=submission,
                reason="该类别标识已被占用（可能在申请之后被创建）",
                base_value=None,
                current_value={"id": existing.id, "keys": list(existing.keys)},
            )
        return None

    if existing is None:
        return Conflict(
            submission=submission,
            reason="类别已从 config.json 中移除",
            base_value=submission.base_value,
            current_value=None,
            missing=True,
        )

    base = submission.base_value if isinstance(submission.base_value, dict) else {}
    current = {"id": existing.id, "keys": list(existing.keys)}
    changed_id = "id" in base and not _same(base.get("id"), current["id"])
    changed_keys = "keys" in base and not _same(base.get("keys"), current["keys"])

    if changed_id or changed_keys:
        return Conflict(
            submission=submission,
            reason="提交后类别信息已被改动",
            base_value=base,
            current_value=current,
        )

    keys = value.get("keys")
    if isinstance(keys, list):
        try:
            store.validate_alias_list(keys, exclude_key=submission.img_key)
        except Exception as error:
            return Conflict(
                submission=submission,
                reason=f"别名现在不可用：{error}",
                base_value=base,
                current_value=current,
            )
    return None


def detect_conflict(store: PickOneStore, submission: Submission) -> Conflict | None:
    """统一的冲突判定入口。"""
    if submission.type in CATEGORY_TYPES:
        return category_conflict(store, submission)
    return image_conflict(store, submission)


# ------------------------------------------------------------------ 应用计划


@dataclass
class ApplyPlan:
    """一次应用要落盘的改动，以及被判定冲突而挂起的提交。"""

    # {img_key: [{"name","field","value","submission_id"}]}
    image_changes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # {img_key: {"id":..., "key":[...]}}
    category_entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    new_keys: list[str] = field(default_factory=list)
    applied_ids: list[int] = field(default_factory=list)
    # submission_id -> 落盘后应记录的值
    applied_values: dict[int, Any] = field(default_factory=dict)
    conflicts: list[Conflict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.applied_ids)


def _dedupe(values: list[str]) -> list[str]:
    """保序去重（大小写不敏感），落盘前再兜一次底。"""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = " ".join(str(value).split())
        if not text:
            continue
        folded = text.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        out.append(text)
    return out


def build_apply_plan(store: PickOneStore, submissions: list[Submission]) -> ApplyPlan:
    """把 approved 提交单分成「可以直接写盘」和「有冲突」两组。

    同一批里可能有多个人改了同一个字段 / 同一个类别（各自基于当时的原值）。
    这时只有排在最前面的那条能写盘，后面的转成冲突交给管理员裁定 ——
    否则先写的那条会被后面的静默覆盖，提交单却还标着「已下发」。
    点赞是增量，叠加起来就是正确结果，不参与这里。
    """
    plan = ApplyPlan()
    ordered = sorted(submissions, key=lambda item: item.id)

    earlier_images: dict[tuple[str, str, str], Submission] = {}
    earlier_categories: dict[str, Submission] = {}

    for submission in ordered:
        name = field_of(submission)
        conflict = detect_conflict(store, submission)

        if conflict is None and submission.type != TYPE_LIKES:
            if name is None:
                earlier = earlier_categories.get(submission.img_key)
            else:
                earlier = earlier_images.get((submission.img_key, submission.target, name))
            if earlier is not None:
                conflict = Conflict(
                    submission=submission,
                    reason=f"同一次下发里另有一条改动（#{earlier.id}）要写同一个"
                    + ("字段" if name else "类别")
                    + "，先写入的那条才是磁盘现值",
                    base_value=submission.base_value,
                    current_value=earlier.submitted_value,
                )

        if conflict is not None:
            plan.conflicts.append(conflict)
            continue

        if name is None:
            earlier_categories[submission.img_key] = submission
            continue

        earlier_images[(submission.img_key, submission.target, name)] = submission
        plan.image_changes.setdefault(submission.img_key, []).append(
            {
                "name": submission.target,
                "field": name,
                "value": submission.submitted_value,
                "submission_id": submission.id,
            }
        )

    conflicted_ids = {conflict.submission.id for conflict in plan.conflicts}

    # 类别改动按 img_key 折叠（同一类别可能既有改 id 又有改别名）
    slots: dict[str, dict[str, Any]] = {}
    for submission in ordered:
        if submission.type not in CATEGORY_TYPES or submission.id in conflicted_ids:
            continue
        value = submission.submitted_value if isinstance(submission.submitted_value, dict) else {}
        slot = slots.setdefault(submission.img_key, {"id": None, "keys": None, "is_new": False})
        if submission.type == TYPE_CATEGORY_CREATE:
            slot["is_new"] = True
            if submission.img_key not in plan.new_keys:
                plan.new_keys.append(submission.img_key)
        if isinstance(value.get("id"), str) and value["id"].strip():
            slot["id"] = value["id"].strip()
        if isinstance(value.get("keys"), list):
            slot["keys"] = [str(item) for item in value["keys"]]

    existing = store.load_categories()
    for img_key, slot in slots.items():
        current = existing.get(img_key)
        if img_key in plan.new_keys or current is None:
            keys = slot["keys"] or [slot["id"] or img_key, img_key]
            entry = {"id": slot["id"] or img_key, "key": _dedupe(keys)}
        else:
            keys = slot["keys"] if slot["keys"] is not None else list(current.keys)
            entry = {"id": slot["id"] or current.id, "key": _dedupe(keys)}
        plan.category_entries[img_key] = entry

    # 记录本批要标记为 applied 的提交单及写入值
    for _img_key, items in plan.image_changes.items():
        for item in items:
            plan.applied_ids.append(item["submission_id"])
            plan.applied_values[item["submission_id"]] = item["value"]

    for submission in ordered:
        if submission.type not in CATEGORY_TYPES or submission.id in conflicted_ids:
            continue
        plan.applied_ids.append(submission.id)
        plan.applied_values[submission.id] = plan.category_entries.get(submission.img_key)

    return plan


def _write_plan(store: PickOneStore, plan: ApplyPlan) -> dict[str, int]:
    """把计划里的内容写盘（不含提交单状态变更）。"""
    image_result = store.apply_image_changes(plan.image_changes)
    category_result = store.apply_category_entries(plan.category_entries)
    for img_key in plan.new_keys:
        store.ensure_category_dir(img_key)
    return {
        "applied_images": image_result["applied"],
        "applied_categories": category_result["applied"],
    }


def apply_approved(repo: Repository, store: PickOneStore) -> dict[str, Any]:
    """一键应用：把 approved 提交单写回，冲突单转 conflict 状态挂起。"""
    submissions = repo.list_approved_submissions()
    if not submissions:
        return {
            "applied_images": 0,
            "applied_categories": 0,
            "new_keys": [],
            "submissions": 0,
            "conflicts": [],
            "details": [],
            "lib_dir": str(store.lib_dir),
        }

    plan = build_apply_plan(store, submissions)

    # 先把冲突挂起来（状态持久化），再写盘；这样即使写盘失败也不会丢冲突信息
    for conflict in plan.conflicts:
        repo.mark_conflict(conflict.submission.id, conflict.to_dict())

    written = _write_plan(store, plan)

    for submission_id in plan.applied_ids:
        repo.mark_applied(submission_id, plan.applied_values.get(submission_id))

    return {
        **written,
        "new_keys": plan.new_keys,
        "submissions": len(plan.applied_ids),
        "conflicts": [conflict.to_dict() for conflict in plan.conflicts],
        "details": [
            {"img_key": img_key, "count": len(items)}
            for img_key, items in plan.image_changes.items()
        ],
        "lib_dir": str(store.lib_dir),
    }


def resolve_conflict(
    repo: Repository,
    store: PickOneStore,
    submission_id: int,
    *,
    keep_new: bool,
    reviewer_id: int,
) -> dict[str, Any]:
    """裁定一条冲突：保留新值并立即写入，或丢弃提交保留磁盘现状。

    注意：选择「保留新值」本身就是管理员的裁定 —— 他知道磁盘当前值和提交值不一样，
    并且决定用提交值覆盖。所以这里**不会**再拿旧的 base_value 去判定冲突，
    只确认目标仍然存在（图片没被删、类别还在），否则拒绝写入。
    """
    submission = repo.get_submission(submission_id)
    if submission is None:
        raise KeyError(submission_id)

    if not keep_new:
        updated = repo.resolve_submission_conflict(
            submission_id, keep_new=False, reviewer_id=reviewer_id
        )
        return {"resolved": "discarded", "applied": False, "submission": updated.to_dict()}

    _ensure_target_writable(store, submission)

    updated = repo.resolve_submission_conflict(
        submission_id, keep_new=True, reviewer_id=reviewer_id
    )

    # 单条写入，不再走冲突判定（原因见上面的 docstring）
    plan = ApplyPlan()
    name = field_of(updated)
    if name is not None:
        plan.image_changes[updated.img_key] = [
            {
                "name": updated.target,
                "field": name,
                "value": updated.submitted_value,
                "submission_id": updated.id,
            }
        ]
        plan.applied_ids.append(updated.id)
        plan.applied_values[updated.id] = updated.submitted_value
    elif updated.type in CATEGORY_TYPES:
        value = updated.submitted_value if isinstance(updated.submitted_value, dict) else {}
        current = store.load_categories().get(updated.img_key)
        if updated.type == TYPE_CATEGORY_CREATE:
            plan.new_keys.append(updated.img_key)
        entry = {
            "id": value.get("id") or (current.id if current else updated.img_key),
            "key": _dedupe(value.get("keys") or (list(current.keys) if current else [])),
        }
        if not entry["key"]:
            entry["key"] = [entry["id"]]
        plan.category_entries[updated.img_key] = entry
        plan.applied_ids.append(updated.id)
        plan.applied_values[updated.id] = entry

    written = _write_plan(store, plan)
    for applied_id in plan.applied_ids:
        repo.mark_applied(applied_id, plan.applied_values.get(applied_id))

    latest = repo.get_submission(submission_id)
    return {
        "resolved": "applied",
        "applied": True,
        **written,
        "submission": latest.to_dict() if latest else updated.to_dict(),
    }


def _ensure_target_writable(store: PickOneStore, submission: Submission) -> None:
    """裁定「保留新值」前的最后一道检查：目标还在不在。

    ApplyConflictError 里的文案是给界面看的；下面这两条属于异常路径，
    所以保持英文，免得被开发模式的 traceback 打进终端。
    """
    if submission.type in CATEGORY_TYPES:
        # 新增类别时目标本来就不存在；改已有类别则要求类别仍在
        if (
            submission.type == TYPE_CATEGORY
            and store.load_categories().get(submission.img_key) is None
        ):
            raise ApplyConflictError("类别已从 config.json 中移除，无法写入")
        return

    try:
        store.get_image_stat(submission.img_key, submission.target)
    except Exception as error:
        raise ApplyConflictError("图片已不存在，无法写入该提交") from error


def image_entry_or_placeholder(store: PickOneStore, img_key: str, name: str) -> dict[str, Any]:
    """图片在 parser.json 里缺记录时使用的占位条目。"""
    path = store.category_dir(img_key) / name
    return new_legacy_entry("", PickOneStore.fallback_add_time(path))
