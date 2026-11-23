"""审计日志写入（敏感操作留痕）"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: int | None = None,
    user_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(AuditLog(
        action=action,
        target_type=target_type,
        target_id=target_id,
        user_id=user_id,
        detail=detail or {},
    ))
    await db.flush()
