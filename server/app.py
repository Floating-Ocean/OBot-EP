"""OBot-EP: web maintenance console for OBot-ACM.

Currently implements Pick-One: fixing meme OCR text, maintaining category
aliases, and reviewing likes/comments through a
"register/login -> submit -> admin review -> one-click apply" workflow.

NOTE: everything logged here must stay ASCII/English so terminals without
CJK fonts do not print mojibake. User-facing API errors may be Chinese.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import admin, auth, categories, images, meta, submissions
from .repository import ROLE_ADMIN, Repository
from .security import generate_password
from .store import NotFoundError, PickOneStore, StoreError, ValidationError

logger = logging.getLogger("obot_ep")

# 会改状态的方法；GET/HEAD/OPTIONS 不改数据，不需要检查来源
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def bootstrap_admin(repo: Repository) -> None:
    """Create the first admin account when the database has no users yet."""
    if repo.count_users() > 0:
        return

    username = config.DEFAULT_ADMIN_USERNAME
    password = config.DEFAULT_ADMIN_PASSWORD or generate_password()
    user = repo.create_user(username, password, display_name="admin", role=ROLE_ADMIN)

    logger.warning("=" * 68)
    logger.warning("Initial admin account created")
    logger.warning("  username: %s", user.username)
    logger.warning("  password: %s", password)
    logger.warning("Change this password after your first login.")
    logger.warning("=" * 68)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config.ensure_dirs()
    repo = Repository()
    app.state.repo = repo
    app.state.store = PickOneStore()

    bootstrap_admin(repo)
    if not config.PICK_ONE_DIR.is_dir():
        logger.warning("Pick-One data directory not found: %s", config.PICK_ONE_DIR)
        logger.warning(
            "Set OBOT_ACM_LIB_DIR to the lib directory of your OBot-ACM checkout."
        )

    logger.info("Pick-One data dir : %s", config.PICK_ONE_DIR)
    logger.info("Local database    : %s", config.DB_PATH)
    logger.info("Frontend dist     : %s", config.FRONTEND_DIST)
    log_exposure_warnings()

    try:
        yield
    finally:
        repo.close()


def _is_network_exposed(bind_host: str) -> bool:
    """绑在回环地址上就不算对外提供服务。"""
    host = (bind_host or "").strip().lower()
    return host not in ("127.0.0.1", "localhost", "::1")


def log_exposure_warnings() -> None:
    """对外提供服务时，把「默认配置在网络里意味着什么」讲清楚。

    不阻止启动 —— 这是使用者的选择 —— 但每一条都是能直接导致事故的默认值，
    所以启动时用 warning 级别重复一遍，而不是只写在 README 里。
    """
    if config.ENABLE_DOCS:
        logger.warning(
            "API docs are ENABLED at /docs (unauthenticated). "
            "Turn off OBOT_EP_ENABLE_DOCS unless you really need them."
        )

    if not _is_network_exposed(config.BIND_HOST):
        return

    logger.warning("=" * 68)
    logger.warning("Listening on %s - reachable from the network.", config.BIND_HOST)
    if not config.COOKIE_SECURE:
        logger.warning(
            "  Traffic is PLAIN HTTP: passwords and session cookies can be read "
            "by anyone on the path. Set OBOT_EP_COOKIE_SECURE=1 behind HTTPS."
        )
    if config.ALLOW_REGISTER:
        logger.warning(
            "  Self-registration is OPEN: anyone who can reach this port can "
            "create an account and submit changes. Set OBOT_EP_ALLOW_REGISTER=0 "
            "if this is not intentional."
        )
    if not config.SESSION_SECRET_FROM_ENV:
        logger.warning(
            "  OBOT_EP_SECRET is not set: the signing key is random per process, "
            "so every restart logs everyone out. Set it for a real deployment."
        )
    if not config.TRUST_PROXY:
        logger.warning(
            "  Behind a reverse proxy, all requests share one rate-limit bucket "
            "unless OBOT_EP_TRUST_PROXY=1 is set."
        )
    logger.warning("  See README 'Listen on the network' before real use.")
    logger.warning("=" * 68)


def _host_of(value: str) -> str:
    """从 Origin / Referer 里取出 host[:port] 并归一化，取不到返回空串。"""
    if not value:
        return ""
    try:
        parts = urlsplit(value)
        host = (parts.hostname or "").casefold()
        port = parts.port  # 端口越界（如 :99999）会在这里抛 ValueError
    except ValueError:
        # 畸形来源头（端口越界、非法 IPv6 等）不该让请求 500，按「取不到」处理；
        # 调用方对空来源的处理是「按跨站拒绝」，所以这是保守方向。
        return ""
    if not host:
        return ""
    if port is None or port == (443 if parts.scheme == "https" else 80):
        return host.rstrip(".")
    return f"{host.rstrip('.')}:{port}"


def _allowed_origins() -> frozenset[str]:
    """额外信任的来源，逗号分隔，形如 `https://obus.example.com`。

    正常部署不需要它：浏览器直接访问本服务时 Origin 与 Host 天然一致。
    只有前面挂了一层会改写 Host 的代理（例如把 API 藏在另一个端口后面）才需要。
    """
    raw = config.EXTRA_TRUSTED_ORIGINS
    if not raw:
        return frozenset()
    items = set()
    for piece in raw.split(","):
        text = piece.strip()
        if text:
            items.add(_host_of(text))
    return frozenset(item for item in items if item)


def _cross_site_request(request: Request) -> bool:
    """判断这个写请求是否来自别的站点（CSRF）。

    会话 Cookie 是 SameSite=Lax，跨站 POST 本来就带不上 Cookie；这里再加一道
    Origin 检查，是为了在「同站子域」或浏览器行为变化时仍然拦得住。
    浏览器无法伪造 Origin，所以只要它和 Host 对不上就能确定是跨站发起的。

    Origin: null（沙箱 iframe / data: 文档 / 某些重定向链）按跨站处理：
    同源的 fetch 永远会带上真实的 Origin，所以这里没有误伤正常前端。
    非浏览器客户端（脚本、curl）不带 Origin / Referer，一律放行。
    """
    origin = request.headers.get("origin")
    if origin is not None:
        source_host = _host_of(origin)
        if not source_host:  # 空值或 "null"
            return True
    else:
        source_host = _host_of(request.headers.get("referer", ""))
        if not source_host:
            return False

    host = _host_of(f"//{request.headers.get('host', '')}")
    if not host:
        return False
    if source_host == host:
        return False
    return source_host not in _allowed_origins()


def _body_too_large(request: Request) -> bool:
    """Content-Length 超过上限就直接拒绝。

    拿不到 Content-Length（分块传输）时放行：这里的目的是挡住「一个匿名请求
    带着几百 MB body」这种廉价打法，不是做完整的请求体限流。
    """
    raw = request.headers.get("content-length")
    if not raw:
        return False
    try:
        length = int(raw)
    except ValueError:
        return True  # 非法的 Content-Length：交给服务器层去拒绝，这里先挡住
    return length > config.MAX_REQUEST_BODY_BYTES


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # 文档接口默认关闭：它们不需要登录，等于把整套接口面公开给任何能连上端口的人
    docs_kwargs: dict = {"docs_url": None, "redoc_url": None, "openapi_url": None}
    if config.ENABLE_DOCS:
        docs_kwargs = {}

    app = FastAPI(
        title="OBot-EP",
        description="Web maintenance console for OBot-ACM (currently: Pick-One)",
        version="0.1.0",
        lifespan=lifespan,
        **docs_kwargs,
    )

    @app.middleware("http")
    async def csrf_origin_guard(request: Request, call_next):
        if request.method in _UNSAFE_METHODS and _cross_site_request(request):
            return JSONResponse(
                status_code=403,
                content={"detail": "拒绝跨站请求（来源校验失败）"},
            )
        if request.method in _UNSAFE_METHODS and _body_too_large(request):
            # 在读请求体之前就拒绝：pydantic 的长度限制要等 body 全部读进内存才生效
            return JSONResponse(
                status_code=413,
                content={"detail": "请求体过大"},
            )
        return await call_next(request)

    @app.exception_handler(StoreError)
    async def store_error_handler(_request: Request, exc: StoreError) -> JSONResponse:
        status_code = 404 if isinstance(exc, NotFoundError) else 400
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """把请求体校验失败整理成简短的英文信息。

        Pydantic 的默认错误文案会带着 schema 里的中文，而这条信息在开发模式下
        会被 uvicorn 打进终端，所以这里只保留字段路径与英文类型名。
        """
        details = [
            {
                "loc": ".".join(str(part) for part in error.get("loc", ())),
                "type": error.get("type", "value_error"),
            }
            for error in exc.errors()
        ]
        summary = "; ".join(f"{item['loc']}: {item['type']}" for item in details) or "invalid request"
        return JSONResponse(
            status_code=422,
            content={
                "detail": f"Request validation failed: {summary}",
                "errors": details,
            },
        )

    for module in (auth, categories, images, submissions, admin, meta):
        app.include_router(module.router, prefix="/api")

    _mount_frontend(app)
    return app


def _mount_frontend(app: FastAPI) -> None:
    """Serve the Vite build output; in development use the Vite dev proxy."""
    dist = config.FRONTEND_DIST
    if not (dist / "index.html").is_file():
        logger.info("No frontend build found at %s - serving API only.", dist)
        logger.info("Run 'npm run dev' in web/ for development, or 'npm run build'.")

        @app.get("/")
        async def api_only_root() -> dict:
            # 不列 /docs：默认是关掉的，列出来只会误导
            return {
                "service": "obot-ep",
                "message": "frontend not built, API is ready",
            }

        return

    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """SPA fallback: serve index.html for non-API paths, files as-is."""
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


app = create_app()
