"""
TalentMatch 后端入口

启动方式（在 backend 目录下）：
    uvicorn app.main:app --reload --port 8000

文档：http://localhost:8000/docs
健康检查：http://localhost:8000/api/v1/healthz
"""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.admin import router as admin_router
from app.api.v1.analytics import router as analytics_router
from app.api.v1.applications import router as applications_router
from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.jobs import router as jobs_router
from app.api.v1.notifications import router as notifications_router
from app.api.v1.rag import router as rag_router
from app.api.v1.skills import router as skills_router
from app.api.v1.candidates import router as candidates_router
from app.api.v1.matching import router as matching_router
from app.core.config import settings
from app.core.database import close_db, init_db
from app.core.logging import logger, setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """启动/关闭钩子"""
    setup_logging()
    logger.info(f"启动 {settings.APP_NAME} v{settings.APP_VERSION} | env={settings.APP_ENV}")
    logger.info(f"数据库: {'SQLite' if settings.is_sqlite else 'PostgreSQL'}")
    logger.info(f"对象存储: {settings.STORAGE_BACKEND}")

    await init_db()
    logger.info("数据库初始化完成（表已就绪）")

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

app.include_router(candidates_router, prefix=settings.API_PREFIX)

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
app.include_router(admin_router, prefix=settings.API_PREFIX)
app.include_router(jobs_router, prefix=settings.API_PREFIX)
app.include_router(skills_router, prefix=settings.API_PREFIX)
app.include_router(matching_router, prefix=settings.API_PREFIX)
app.include_router(applications_router, prefix=settings.API_PREFIX)
app.include_router(notifications_router, prefix=settings.API_PREFIX)
app.include_router(analytics_router, prefix=settings.API_PREFIX)
app.include_router(rag_router, prefix=settings.API_PREFIX)


@app.get("/", tags=["系统"], summary="根路径")
async def root() -> dict:
    return {
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": f"{settings.API_PREFIX}/healthz",
    }
