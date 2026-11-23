"""
健康检查接口

/healthz 用于：本机联调、Docker healthcheck、部署后自检。
返回数据库与对象存储的真实状态，而不是永远返回 ok。
"""
from fastapi import APIRouter

from app.core.config import settings
from app.core.database import check_db
from app.core.storage import get_storage

router = APIRouter(tags=["系统"])


@router.get("/healthz", summary="健康检查")
async def healthz() -> dict:
    """
    检查数据库与对象存储

    status:
      - ok        全部正常
      - degraded  部分异常（服务仍可启动，但相关功能不可用）
    """
    db_ok, db_detail = await check_db()

    try:
        storage_ok, storage_detail = get_storage().health_check()
    except Exception as exc:  # noqa: BLE001
        storage_ok, storage_detail = False, f"{type(exc).__name__}: {exc}"

    queue_info = await _check_queue()

    all_ok = db_ok and storage_ok and queue_info["ok"]
    return {
        "status": "ok" if all_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
        "components": {
            "database": {"ok": db_ok, "detail": db_detail, "backend": "sqlite" if settings.is_sqlite else "postgresql"},
            "storage": {"ok": storage_ok, "detail": storage_detail, "backend": settings.STORAGE_BACKEND},
            "queue": queue_info,
        },
    }


async def _check_queue() -> dict:
    """队列健康状态：memory 恒可用；celery 需要 Redis 可达"""
    if not settings.celery_enabled:
        return {"ok": True, "backend": "memory", "detail": "进程内 BackgroundTasks"}
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        try:
            pong = await client.ping()
        finally:
            await client.aclose()
        return {"ok": bool(pong), "backend": "celery", "detail": settings.REDIS_URL}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "backend": "celery", "detail": f"{type(exc).__name__}: {exc}"}
