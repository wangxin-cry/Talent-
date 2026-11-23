"""API Key 业务逻辑"""
from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import sha256_hex
from app.models.api_key import ApiKey
from app.models.base import utcnow
from app.models.user import STATUS_ACTIVE, User
from app.schemas.admin import ApiKeyCreateIn, ApiKeyOut
from app.services import system_config


def key_status(key: ApiKey, now=None) -> str:
    now = now or utcnow()
    if key.revoked_at:
        return "revoked"
    if key.expires_at and key.expires_at <= now:
        return "expired"
    return "active"


def to_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        name=key.name,
        prefix=key.prefix,
        last_used_at=key.last_used_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        create_time=key.create_time,
        status=key_status(key),
    )


async def create_key(
    db: AsyncSession, data: ApiKeyCreateIn, user_id: int
) -> tuple[ApiKey, str]:
    """创建 API Key，返回（记录, 明文）；明文只返回这一次"""
    raw = "tm_" + secrets.token_urlsafe(32)
    expires_at = None
    if data.expires_in_days:
        expires_at = utcnow() + timedelta(days=data.expires_in_days)
    key = ApiKey(
        user_id=user_id,
        name=data.name.strip(),
        prefix=raw[:11],
        key_hash=sha256_hex(raw),
        expires_at=expires_at,
    )
    db.add(key)
    await db.flush()
    return key, raw


async def list_keys(db: AsyncSession, user_id: int) -> list[ApiKey]:
    rows = await db.execute(
        select(ApiKey)
        .where(ApiKey.user_id == user_id)
        .order_by(ApiKey.create_time.desc(), ApiKey.id.desc())
    )
    return list(rows.scalars().all())


async def get_key_or_404(
    db: AsyncSession, key_id: int, company_id: int | None = None
) -> ApiKey:
    key = await db.get(ApiKey, key_id)
    if key is None or (company_id is not None and key.company_id != company_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API Key 不存在")
    return key


def revoke(key: ApiKey) -> None:
    if key.revoked_at is None:
        key.revoked_at = utcnow()


async def authenticate(db: AsyncSession, raw: str) -> User | None:
    """用明文 API Key 找到有效用户；无效/过期/吊销/禁用都返回 None"""
    if not raw:
        return None
    if await system_config.get_value(db, "security.api_key_enabled") is False:
        return None
    rows = await db.execute(
        select(ApiKey).where(ApiKey.key_hash == sha256_hex(raw))
    )
    key = rows.scalar_one_or_none()
    if key is None or key_status(key) != "active":
        return None
    user = await db.get(User, key.user_id)
    if user is None or user.status != STATUS_ACTIVE:
        return None
    key.last_used_at = utcnow()
    await db.commit()
    return user


async def list_all_keys(
    db: AsyncSession, company_id: int | None = None
) -> list[tuple[ApiKey, str | None]]:
    query = select(ApiKey, User.name).outerjoin(User, User.id == ApiKey.user_id)
    if company_id is not None:
        query = query.where(ApiKey.company_id == company_id)
    rows = await db.execute(query.order_by(ApiKey.create_time.desc(), ApiKey.id.desc()))
    return [(key, name) for key, name in rows.all()]
