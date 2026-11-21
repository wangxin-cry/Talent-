"""站内通知接口"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, DbSession
from app.models.candidate import Candidate
from app.schemas.application import (
    NotificationListOut,
    NotificationOut,
    UnreadCountOut,
)
from app.services import notifications as notification_svc

router = APIRouter(prefix="/notifications", tags=["通知"])


async def _to_out(db: AsyncSession, notification) -> NotificationOut:
    candidate = (
        await db.get(Candidate, notification.candidate_id)
        if notification.candidate_id
        else None
    )
    item = NotificationOut.model_validate(notification)
    return item.model_copy(
        update={"candidate_name": candidate.name if candidate else None}
    )


@router.get("", response_model=NotificationListOut, summary="当前用户的站内通知")
async def list_api(
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
) -> NotificationListOut:
    rows, unread = await notification_svc.list_notifications(
        db, user.id, unread_only=unread_only, limit=limit
    )
    items = [await _to_out(db, row) for row in rows]
    return NotificationListOut(items=items, total=len(items), unread=unread)


@router.get("/unread-count", response_model=UnreadCountOut, summary="未读通知数")
async def unread_api(db: DbSession, user: CurrentUser) -> UnreadCountOut:
    return UnreadCountOut(unread=await notification_svc.unread_count(db, user.id))


@router.post(
    "/{notification_id}/read", response_model=NotificationOut, summary="标记已读"
)
async def read_api(
    notification_id: int, db: DbSession, user: CurrentUser
) -> NotificationOut:
    notification = await notification_svc.mark_read(db, notification_id, user.id)
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在"
        )
    return await _to_out(db, notification)
