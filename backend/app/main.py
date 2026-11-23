"""
TalentMatch 后端入口

启动方式（在 backend 目录下）：
    uvicorn app.main:app --reload --port 8000

文档：http://localhost:8000/docs
健康检查：http://localhost:8000/api/v1/healthz
"""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.admin import router as admin_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.api_keys import router as api_keys_router
from app.api.v1.applications import router as applications_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.interviews import router as interviews_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.orchestration import router as orchestration_router
from app.api.v1.public import router as public_router
from app.api.v1.rag import router as rag_router
from app.api.v1.skills import router as skills_router
from app.api.v1.candidates import router as candidates_router
from app.api.v1.chat import router as chat_router
from app.api.v1.company import router as company_router
from app.api.v1.matching import router as matching_router
from app.api.v1.platform import router as platform_router
from app.core.config import settings
from app.core.database import SessionLocal, close_db, init_db
from app.core.logging import logger, setup_logging
from app.core.rate_limit import RateLimitMiddleware
from app.services import company as company_service


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动/关闭钩子"""
    setup_logging()
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION} | env={settings.APP_ENV}")
    logger.info(f"数据库: {'SQLite' if settings.is_sqlite else 'PostgreSQL'}")
    logger.info(f"对象存储: {settings.STORAGE_BACKEND}")

    await init_db()
    async with SessionLocal() as session:
        await company_service.ensure_default_company(session)
    logger.info("数据库初始化完成（表与默认公司已就绪）")

    yield

    await close_db()
    logger.info("应用已关闭")


app = FastAPI(
    title=f"{settings.APP_NAME} API",
    version=settings.APP_VERSION,
    description="AI 驱动的企业智能招聘 Agent 平台",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS（开发期允许前端 5173；生产收紧白名单）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
)

# 全局限流（PRD §8.3）：每用户 100 次/分钟，超限返回 429
app.add_middleware(RateLimitMiddleware)

@app.middleware("http")
async def add_process_time(request: Request, call_next):
    """在响应头带处理耗时，便于前端/压测观察"""
    import time

    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.1f}ms"
    return response


# ---------------------------------------------------------------- 异常处理
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """统一 HTTP 异常结构"""
    logger.warning(f"HTTP {exc.status_code} | {request.method} {request.url.path} | {exc.detail}")
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": {"code": exc.status_code, "message": exc.detail},
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常：对外不暴露堆栈"""
    logger.exception(f"未处理异常 | {request.method} {request.url.path} | {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": {
                "code": 500,
                "message": str(exc) if settings.DEBUG else "服务器内部错误，请稍后重试",
            },
        },
    )


# ---------------------------------------------------------------- 路由
app.include_router(health_router, prefix=settings.API_PREFIX)
app.include_router(auth_router, prefix=settings.API_PREFIX)
app.include_router(company_router, prefix=settings.API_PREFIX)
app.include_router(platform_router, prefix=settings.API_PREFIX)
app.include_router(admin_router, prefix=settings.API_PREFIX)
app.include_router(api_keys_router, prefix=settings.API_PREFIX)
app.include_router(jobs_router, prefix=settings.API_PREFIX)
app.include_router(skills_router, prefix=settings.API_PREFIX)
app.include_router(candidates_router, prefix=settings.API_PREFIX)
app.include_router(matching_router, prefix=settings.API_PREFIX)
app.include_router(applications_router, prefix=settings.API_PREFIX)
app.include_router(interviews_router, prefix=settings.API_PREFIX)
app.include_router(public_router, prefix=settings.API_PREFIX)
app.include_router(notifications_router, prefix=settings.API_PREFIX)
app.include_router(analytics_router, prefix=settings.API_PREFIX)
app.include_router(rag_router, prefix=settings.API_PREFIX)
app.include_router(orchestration_router, prefix=settings.API_PREFIX)
app.include_router(chat_router, prefix=settings.API_PREFIX)


@app.get("/", tags=["系统"], summary="根路径")
async def root():
    if _SPA_INDEX is not None:
        return FileResponse(_SPA_INDEX)
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": f"{settings.API_PREFIX}/healthz",
    }


# ---------------------------------------------------------------- 前端静态托管
# 开启 SERVE_FRONTEND 后，构建产物由后端同端口托管（生产单进程部署）；
# /api、/docs 等仍走各自的接口，其余路径回退到 index.html 支持前端路由。
def _resolve_dist() -> Path:
    if settings.FRONTEND_DIST:
        return Path(settings.FRONTEND_DIST)
    return Path(__file__).resolve().parents[2] / "frontend" / "dist"


_SPA_INDEX: Path | None = None
if settings.SERVE_FRONTEND:
    _dist = _resolve_dist()
    if (_dist / "index.html").exists():
        _SPA_INDEX = _dist / "index.html"
        if (_dist / "assets").exists():
            app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api/", "docs", "redoc", "openapi.json")):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = _dist / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(_SPA_INDEX)
    else:
        logger.warning(f"未找到前端构建产物：{_dist}，请先执行 npm run build")
