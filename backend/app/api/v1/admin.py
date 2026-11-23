"""
管理员接口

前缀：/api/v1/admin
整个路由由 require_admin 保护：非 admin 角色一律 403。

包含：
- 用户管理：列表 / 改角色 / 改部门 / 禁用 / 软删除
- 系统配置：查看 / 修改
- 审计日志：查询
- API Key：查看全部 / 吊销
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from loguru import logger
from sqlalchemy import func, or_, select

from app.core.deps import DbSession, require_admin
from app.core.storage import get_storage
from app.core.tenant import get_company_id, require_company_id
from app.models.audit import AuditLog
from app.models.user import (
    ROLE_ADMIN,
    STATUS_ACTIVE,
    STATUS_DELETED,
    STATUS_DISABLED,
    User,
)
from app.schemas.admin import (
    AdminApiKeyListOut,
    AdminApiKeyOut,
    AdminUserOut,
    AdminUserUpdateIn,
    AuditLogListOut,
    AuditLogOut,
    SystemConfigOut,
    SystemConfigUpdateIn,
)
from app.services import api_keys as api_key_service
from app.services import audit
from app.services import system_config as config_service

router = APIRouter(
    prefix="/admin",
    tags=["管理员"],
    dependencies=[Depends(require_admin)],
)


async def _active_admin_count(db: DbSession, exclude_id: int | None = None) -> int:
    conditions = [
        User.role == ROLE_ADMIN,
        User.status == STATUS_ACTIVE,
        User.company_id == require_company_id(),
    ]
    if exclude_id is not None:
        conditions.append(User.id != exclude_id)
    return (
        await db.execute(select(func.count()).select_from(User).where(*conditions))
    ).scalar_one()


@router.get("/users", response_model=list[AdminUserOut], summary="用户列表")
async def list_users(
    db: DbSession,
    q: str | None = Query(default=None, max_length=100),
    role: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    include_deleted: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=200),
) -> list[AdminUserOut]:
    conditions = [User.company_id == require_company_id()]
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        conditions.append(or_(User.name.ilike(keyword), User.email.ilike(keyword)))
    if role:
        conditions.append(User.role == role)
    if status_filter:
        conditions.append(User.status == status_filter)
    elif not include_deleted:
        conditions.append(User.status != STATUS_DELETED)

    rows = await db.execute(
        select(User)
        .where(*conditions)
        .order_by(User.id)
        .offset(skip)
        .limit(limit)
    )
    return [AdminUserOut.model_validate(user) for user in rows.scalars().all()]


@router.patch("/users/{user_id}", response_model=AdminUserOut, summary="修改角色/部门/状态")
async def update_user(
    user_id: int,
    data: AdminUserUpdateIn,
    db: DbSession,
    actor: User = Depends(require_admin),
) -> AdminUserOut:
    target = await db.get(User, user_id)
    if (
        target is None
        or target.status == STATUS_DELETED
        or target.company_id != actor.company_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    updates = data.model_dump(exclude_unset=True)
    new_role = updates.get("role", target.role)
    new_status = updates.get("status", target.status)

    if target.id == actor.id:
        if "role" in updates and new_role != target.role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色")
        if "status" in updates and new_status != STATUS_ACTIVE:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能禁用自己")

    demoting_admin = (
        target.role == ROLE_ADMIN
        and target.status == STATUS_ACTIVE
        and (new_role != ROLE_ADMIN or new_status != STATUS_ACTIVE)
    )
    if demoting_admin and await _active_admin_count(db, target.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少保留一名启用状态的管理员",
        )

    before = {
        "role": target.role,
        "status": target.status,
        "department": target.department,
    }
    if "role" in updates:
        target.role = new_role
    if "department" in updates:
        target.department = (updates["department"] or "").strip() or None
    if "status" in updates and new_status != target.status:
        target.status = new_status
        if new_status == STATUS_DISABLED:
            target.token_version += 1

    await audit.write_audit(
        db,
        action="admin.user.update",
        target_type="user",
        target_id=target.id,
        user_id=actor.id,
        detail={
            "before": before,
            "after": {
                "role": target.role,
                "status": target.status,
                "department": target.department,
            },
        },
    )
    await db.commit()
    await db.refresh(target)
    return AdminUserOut.model_validate(target)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除用户（软删除）")
async def delete_user(
    user_id: int,
    db: DbSession,
    actor: User = Depends(require_admin),
) -> None:
    target = await db.get(User, user_id)
    if (
        target is None
        or target.status == STATUS_DELETED
        or target.company_id != actor.company_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    if target.id == actor.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能删除自己")
    if target.role == ROLE_ADMIN and await _active_admin_count(db, target.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="至少保留一名启用状态的管理员",
        )

    original = {"name": target.name, "email": target.email, "role": target.role}
    avatar_key = target.avatar_key
    target.status = STATUS_DELETED
    target.token_version += 1
    # 释放唯一登录名/邮箱，允许以后重新注册；审计里保留原值
    target.name = f"deleted_{target.id}"
    target.email = f"deleted_{target.id}@talentmatch.invalid"
    target.phone = None
    target.avatar_key = None
    target.department = None

    await audit.write_audit(
        db,
        action="admin.user.delete",
        target_type="user",
        target_id=target.id,
        user_id=actor.id,
        detail={"original": original},
    )
    await db.commit()

    if avatar_key:
        try:
            get_storage().delete(avatar_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"删除用户时清理头像失败 | key={avatar_key} | {exc}")


@router.get("/system-config", response_model=list[SystemConfigOut], summary="系统配置列表")
async def list_system_config(db: DbSession) -> list[SystemConfigOut]:
    return [SystemConfigOut.model_validate(item) for item in await config_service.list_configs(db)]


@router.put("/system-config/{key}", response_model=SystemConfigOut, summary="修改系统配置")
async def update_system_config(
    key: str,
    data: SystemConfigUpdateIn,
    db: DbSession,
    actor: User = Depends(require_admin),
) -> SystemConfigOut:
    row = await config_service.upsert_config(db, key, data.value, data.description, actor.id)
    await audit.write_audit(
        db,
        action="admin.config.update",
        target_type="system_config",
        target_id=row.id,
        user_id=actor.id,
        detail={"key": key, "value": data.value},
    )
    await db.commit()
    await db.refresh(row)
    return SystemConfigOut.model_validate(row)


@router.get("/audit-logs", response_model=AuditLogListOut, summary="审计日志")
async def list_audit_logs(
    db: DbSession,
    action: str | None = Query(default=None, max_length=50),
    target_type: str | None = Query(default=None, max_length=50),
    user_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> AuditLogListOut:
    conditions = [AuditLog.company_id == require_company_id()]
    if action:
        conditions.append(AuditLog.action == action)
    if target_type:
        conditions.append(AuditLog.target_type == target_type)
    if user_id:
        conditions.append(AuditLog.user_id == user_id)

    total = (
        await db.execute(select(func.count()).select_from(AuditLog).where(*conditions))
    ).scalar_one()
    rows = await db.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.user_id)
        .where(*conditions)
        .order_by(AuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    items = [
        AuditLogOut(
            id=log.id,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            detail=log.detail or {},
            user_id=log.user_id,
            user_name=name,
            create_time=log.create_time,
        )
        for log, name in rows.all()
    ]
    return AuditLogListOut(items=items, total=total)


@router.get("/api-keys", response_model=AdminApiKeyListOut, summary="全部 API Key")
async def list_all_api_keys(db: DbSession) -> AdminApiKeyListOut:
    items = [
        AdminApiKeyOut(
            **api_key_service.to_out(key).model_dump(),
            user_id=key.user_id,
            user_name=name,
        )
        for key, name in await api_key_service.list_all_keys(db, get_company_id())
    ]
    return AdminApiKeyListOut(items=items)


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="吊销 API Key")
async def revoke_api_key(
    key_id: int,
    db: DbSession,
    actor: User = Depends(require_admin),
) -> None:
    key = await api_key_service.get_key_or_404(db, key_id, get_company_id())
    api_key_service.revoke(key)
    await audit.write_audit(
        db,
        action="api_key.revoke",
        target_type="api_key",
        target_id=key.id,
        user_id=actor.id,
        detail={"owner_id": key.user_id, "name": key.name},
    )
    await db.commit()
