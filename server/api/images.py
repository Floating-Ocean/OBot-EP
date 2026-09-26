"""图片浏览与文件服务路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, Response as RawResponse

from .. import config
from ..changes import effective_image, image_pending_changes, load_open_submissions
from ..hashing import base62_to_md5, hash_id_of, make_thumbnail, thumbnail_cache_key
from ..palette import accent_of
from ..store import NotFoundError, StoreError, ValidationError
from .deps import CurrentUser, Repo, Store

router = APIRouter(prefix="/images", tags=["images"])

_GIF_MEDIA_TYPE = "image/gif"


def _stat_to_payload(stat) -> dict:
    """把 ImageStat 转成前端需要的短结构（不含 pending 覆盖）。"""
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
    }


@router.get("/{img_key}")
def list_images(
    img_key: str,
    repo: Repo,
    store: Store,
    user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=60, ge=1, le=200),
    q: str = Query(default="", max_length=64),
    filter: str = Query(default="all", pattern="^(all|missing_ocr|has_change)$"),
    sort: str = Query(default="hash", pattern="^(hash|likes|comments|add_time|pickup_times)$"),
    order: str = Query(default="asc", pattern="^(asc|desc)$"),
) -> dict:
    """分页列出某个类别下的表情包。

    字段值都是磁盘原值；审核中的改动放在 pending_changes 里，只有自己的那条
    会带 mine=true（前端从它接着改，别人的只能看）。
    """
    try:
        store.category_or_404(img_key)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    pending = image_pending_changes(load_open_submissions(repo)).get(img_key, {})

    stats = list(store.iter_image_stats(img_key))

    needle = q.strip().casefold()
    if needle:
        stats = [
            item
            for item in stats
            if needle in item.ocr_text.casefold()
            or needle in item.hash_id.casefold()
            or needle in item.name.casefold()
        ]

    if filter == "missing_ocr":
        stats = [item for item in stats if item.needs_ocr]
    elif filter == "has_change":
        stats = [item for item in stats if item.name in pending]

    if sort == "hash":
        stats.sort(key=lambda item: item.name, reverse=(order == "desc"))
    elif sort == "likes":
        stats.sort(key=lambda item: (item.likes, item.name), reverse=(order == "desc"))
    elif sort == "comments":
        stats.sort(key=lambda item: (len(item.comments), item.name), reverse=(order == "desc"))
    elif sort == "add_time":
        stats.sort(key=lambda item: (item.add_time, item.name), reverse=(order == "desc"))
    else:
        stats.sort(key=lambda item: (item.pickup_times, item.name), reverse=(order == "desc"))

    total = len(stats)
    start = (page - 1) * page_size
    page_items = stats[start : start + page_size]

    return {
        "img_key": img_key,
        "total": total,
        "page": page,
        "page_size": page_size,
        "missing_ocr_in_view": sum(1 for item in page_items if item.needs_ocr),
        "items": [
            effective_image(item, pending.get(item.name), viewer_id=user.id)
            for item in page_items
        ],
    }


@router.get("/{img_key}/stats")
def image_stats(img_key: str, repo: Repo, store: Store, _user: CurrentUser) -> dict:
    """类别级统计，用于页面上的进度提示。"""
    try:
        store.category_or_404(img_key)
    except NotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    total = 0
    missing = 0
    legacy = 0
    likes = 0
    for stat in store.iter_image_stats(img_key):
        total += 1
        missing += 1 if stat.needs_ocr else 0
        legacy += 1 if stat.legacy else 0
        likes += stat.likes

    # 有多少张图带着待处理的改动（筛选按钮上要显示数量）
    pending = image_pending_changes(load_open_submissions(repo)).get(img_key, {})

    return {
        "img_key": img_key,
        "total": total,
        "missing_ocr": missing,
        "legacy_entries": legacy,
        "total_likes": likes,
        "pending_changes": len(pending),
    }


@router.get("/{img_key}/item/{name}")
def image_detail(img_key: str, name: str, repo: Repo, store: Store, user: CurrentUser) -> dict:
    try:
        stat = store.get_image_stat(img_key, name)
    except (NotFoundError, ValidationError, StoreError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    pending = image_pending_changes(load_open_submissions(repo)).get(img_key, {})
    payload = effective_image(stat, pending.get(name), viewer_id=user.id)
    payload["accent"] = accent_of(img_key)
    return {"image": payload}


@router.get("/{img_key}/raw/{name}")
def raw_image(img_key: str, name: str, store: Store, _user: CurrentUser) -> FileResponse:
    """原图（GIF）。"""
    try:
        path = store.image_path(img_key, name)
    except (NotFoundError, ValidationError, StoreError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    return FileResponse(
        path,
        media_type=_GIF_MEDIA_TYPE,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/{img_key}/thumb/{name}")
def thumbnail(img_key: str, name: str, store: Store, _user: CurrentUser) -> RawResponse:
    """缩略图（WebP，磁盘缓存）。动图只取前几帧，避免一次解码上千张。"""
    try:
        path = store.image_path(img_key, name)
    except (NotFoundError, ValidationError, StoreError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error

    stat = path.stat()
    cache_key = thumbnail_cache_key(str(path), stat.st_mtime_ns, stat.st_size)
    cache_path = config.THUMB_DIR / f"{cache_key}.webp"

    if cache_path.is_file():
        return RawResponse(
            content=cache_path.read_bytes(),
            media_type="image/webp",
            headers={"Cache-Control": "private, max-age=604800"},
        )

    try:
        data = make_thumbnail(path.read_bytes())
    except Exception as error:  # 坏图不应该把整个页面拖垮
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"无法生成缩略图: {error}",
        ) from error

    config.THUMB_DIR.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_bytes(data)
    except OSError:
        pass

    return RawResponse(
        content=data,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=604800"},
    )


@router.get("/{img_key}/hash-id/{hash_id}")
def lookup_by_hash_id(img_key: str, hash_id: str, store: Store, _user: CurrentUser) -> dict:
    """按 Bot 回复里的 Base62 ID 反查图片。"""
    try:
        md5 = base62_to_md5(hash_id)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    name = f"{md5}.gif"
    try:
        stat = store.get_image_stat(img_key, name)
    except (NotFoundError, ValidationError, StoreError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    return {"image": _stat_to_payload(stat), "name": name, "hash_id": hash_id_of(md5)}
