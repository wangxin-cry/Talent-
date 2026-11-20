"""
管理员接口

前缀：/api/v1/admin
整个路由由 require_admin 保护：非 admin 角色一律 403。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.core.deps import DbSession, require_admin
from app.models.user import User
from app.schemas.auth import UserOut

router = APIRouter(
    prefix="/admin",
    tags=["管理员"],
    dependencies=[Depends(require_admin)],
)


@router.get("/users", response_model=list[UserOut], summary="用户列表")
async def list_users(
    db: DbSession,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[UserOut]:
    result = await db.execute(select(User).order_by(User.id).offset(skip).limit(limit))
    return [UserOut.model_validate(user) for user in result.scalars().all()]
