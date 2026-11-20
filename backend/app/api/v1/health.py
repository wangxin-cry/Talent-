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

    all_ok = db_ok and storage_ok
    return {
        "status": "ok" if all_ok else "degraded",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "env": settings.APP_ENV,
        "components": {
            "database": {"ok": db_ok, "detail": db_detail, "backend": "sqlite" if settings.is_sqlite else "postgresql"},
            "storage": {"ok": storage_ok, "detail": storage_detail, "backend": settings.STORAGE_BACKEND},
        },
    }
