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

    try:
        yield
    finally:
        repo.close()


def create_app() -> FastAPI:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = FastAPI(
        title="OBot-EP",
        description="Web maintenance console for OBot-ACM (currently: Pick-One)",
        version="0.1.0",
        lifespan=lifespan,
    )

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
            return {
                "service": "obot-ep",
                "message": "frontend not built, API is ready",
                "docs": "/docs",
                "frontend_dist": str(dist),
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
