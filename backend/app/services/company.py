"""
公司（租户）服务

- 注册建司 / 邀请码入司
- 公司管理员维护成员与邀请码
- 平台超管管理公司状态
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import (
    STATUS_ACTIVE,
    STATUS_DISABLED,
    Company,
    generate_invite_code,
    generate_slug,
)
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, ROLE_RECRUITER, STATUS_ACTIVE as USER_ACTIVE, User

ASSIGNABLE_ROLES = (ROLE_RECRUITER, ROLE_MANAGER, ROLE_ADMIN)


async def create_company(db: AsyncSession, name: str, creator_id: int | None = None) -> Company:
    """创建公司；名称唯一，邀请码与 slug 自动生成"""
    name = name.strip()
    exists = await db.execute(select(Company.id).where(Company.name == name))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="公司名称已存在")

    for _ in range(5):
        slug = generate_slug()
        if (await db.execute(select(Company.id).where(Company.slug == slug))).scalar_one_or_none() is None:
            break
    else:  # pragma: no cover - 概率极低
        raise HTTPException(status_code=500, detail="生成公司标识失败，请重试")

    company = Company(
        name=name,
        slug=slug,
        invite_code=generate_invite_code(),
        status=STATUS_ACTIVE,
        created_by=creator_id,
    )
    db.add(company)
    await db.flush()
    return company


async def get_by_invite(db: AsyncSession, invite_code: str) -> Company:
    normalized = invite_code.strip().upper()
    company = (
        await db.execute(select(Company).where(Company.invite_code == normalized))
    ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="邀请码无效")
    if company.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该公司已停用")
    return company


async def get_by_slug(db: AsyncSession, slug: str) -> Company:
    company = (
        await db.execute(select(Company).where(Company.slug == slug.strip()))
    ).scalar_one_or_none()
    if company is None or company.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在或已停用")
    return company


async def get_active_company(db: AsyncSession, company_id: int) -> Company | None:
    company = await db.get(Company, company_id)
    if company is None or company.status != STATUS_ACTIVE:
        return None
    return company


async def lookup_by_invite(db: AsyncSession, invite_code: str) -> Company:
    """注册页回显公司名（不暴露成员等敏感信息）"""
    return await get_by_invite(db, invite_code)


async def reset_invite_code(db: AsyncSession, company_id: int) -> Company:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    for _ in range(5):
        code = generate_invite_code()
        if (
            await db.execute(select(Company.id).where(Company.invite_code == code))
        ).scalar_one_or_none() is None:
            company.invite_code = code
            break
    await db.commit()
    await db.refresh(company)
    return company


async def list_members(db: AsyncSession, company_id: int) -> list[User]:
    rows = await db.execute(
        select(User).where(User.company_id == company_id).order_by(User.id)
    )
    return list(rows.scalars().all())


async def update_member(
    db: AsyncSession,
    company_id: int,
    user_id: int,
    *,
    role: str | None = None,
    member_status: str | None = None,
) -> User:
    """公司管理员调整成员角色 / 启用停用（不能操作自己）"""
    member = await db.get(User, user_id)
    if member is None or member.company_id != company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="成员不存在")
    if role is not None:
        if role not in ASSIGNABLE_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="角色不合法")
        member.role = role
    if member_status is not None:
        if member_status not in (USER_ACTIVE, "disabled"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="状态不合法")
        member.status = member_status
    await db.commit()
    await db.refresh(member)
    return member


async def list_all(db: AsyncSession) -> list[tuple[Company, int]]:
    """平台超管：公司列表 + 成员数"""
    rows = await db.execute(
        select(Company, func.count(User.id))
        .outerjoin(User, User.company_id == Company.id)
        .group_by(Company.id)
        .order_by(Company.id)
    )
    return [(company, int(count)) for company, count in rows.all()]


async def set_status(db: AsyncSession, company_id: int, new_status: str) -> Company:
    if new_status not in (STATUS_ACTIVE, STATUS_DISABLED):
        raise HTTPException(status_code=400, detail="公司状态不合法")
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="公司不存在")
    company.status = new_status
    await db.commit()
    await db.refresh(company)
    return company


async def ensure_default_company(db: AsyncSession) -> Company:
    """确保默认公司（id=1）存在：存量数据与旧测试都归属它"""
    existing = await db.get(Company, 1)
    if existing is not None:
        return existing
    company = Company(
        id=1,
        name="默认公司",
        slug=generate_slug(),
        invite_code=generate_invite_code(),
        status=STATUS_ACTIVE,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    # 显式插入 id=1 不会推进自增序列，需手动对齐，避免后续建司主键冲突
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text(
                "SELECT setval(pg_get_serial_sequence('company', 'id'), "
                "(SELECT COALESCE(MAX(id), 1) FROM company))"
            )
        )
        await db.commit()
    return company


def to_out(company: Company, *, include_invite: bool = False) -> dict:
    data = {
        "id": company.id,
        "name": company.name,
        "slug": company.slug,
        "status": company.status,
        "create_time": company.create_time,
    }
    if include_invite:
        data["invite_code"] = company.invite_code
    return data
