"""用户自己的 API Key 管理：创建 / 查看 / 吊销"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.admin import ApiKeyCreateIn, ApiKeyCreatedOut, ApiKeyListOut
from app.services import api_keys as api_key_service
from app.services import audit

router = APIRouter(prefix="/api-keys", tags=["API Key"])


@router.get("", response_model=ApiKeyListOut, summary="我的 API Key")
async def list_my_keys(db: DbSession, user: CurrentUser) -> ApiKeyListOut:
    keys = await api_key_service.list_keys(db, user.id)
    return ApiKeyListOut(items=[api_key_service.to_out(key) for key in keys])


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED, summary="创建 API Key")
async def create_my_key(
    data: ApiKeyCreateIn, db: DbSession, user: CurrentUser
) -> ApiKeyCreatedOut:
    key, raw = await api_key_service.create_key(db, data, user.id)
    await audit.write_audit(
        db,
        action="api_key.create",
        target_type="api_key",
        target_id=key.id,
        user_id=user.id,
        detail={"name": key.name, "prefix": key.prefix},
    )
    await db.commit()
    await db.refresh(key)
    return ApiKeyCreatedOut(
        **api_key_service.to_out(key).model_dump(),
        key=raw,
    )


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="吊销我的 API Key")
async def revoke_my_key(key_id: int, db: DbSession, user: CurrentUser) -> None:
    key = await api_key_service.get_key_or_404(db, key_id)
    if key.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key 不存在")
    api_key_service.revoke(key)
    await audit.write_audit(
        db,
        action="api_key.revoke",
        target_type="api_key",
        target_id=key.id,
        user_id=user.id,
        detail={"name": key.name},
    )
    await db.commit()
