"""平台超管后台：公司管理（跨租户）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import DbSession, require_superadmin
from app.models.user import User
from app.schemas.company import (
    CompanyMemberOut,
    CompanyMemberUpdateIn,
    PlatformCompanyCreateIn,
    PlatformCompanyOut,
    PlatformCompanyUpdateIn,
)
from app.services import company as company_service

router = APIRouter(prefix="/platform", tags=["平台管理"])


def _to_out(company, member_count: int = 0) -> PlatformCompanyOut:
    return PlatformCompanyOut(
        id=company.id,
        name=company.name,
        slug=company.slug,
        status=company.status,
        invite_code=company.invite_code,
        member_count=member_count,
        create_time=company.create_time,
    )


@router.get(
    "/companies", response_model=list[PlatformCompanyOut], summary="公司列表（超管）"
)
async def list_companies(db: DbSession, _: User = Depends(require_superadmin)):
    rows = await company_service.list_all(db)
    return [_to_out(company, count) for company, count in rows]


@router.post(
    "/companies",
    response_model=PlatformCompanyOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建公司（超管）",
)
async def create_company(
    payload: PlatformCompanyCreateIn,
    db: DbSession,
    _: User = Depends(require_superadmin),
) -> PlatformCompanyOut:
    company = await company_service.create_company(db, payload.name)
    await db.commit()
    await db.refresh(company)
    return _to_out(company)


@router.patch(
    "/companies/{company_id}",
    response_model=PlatformCompanyOut,
    summary="启用 / 停用公司（超管）",
)
async def update_company(
    company_id: int,
    payload: PlatformCompanyUpdateIn,
    db: DbSession,
    _: User = Depends(require_superadmin),
) -> PlatformCompanyOut:
    company = await company_service.set_status(db, company_id, payload.status)
    rows = await company_service.list_all(db)
    count = next((n for c, n in rows if c.id == company.id), 0)
    return _to_out(company, count)


@router.patch(
    "/companies/{company_id}/members/{member_id}",
    response_model=CompanyMemberOut,
    summary="设置公司管理员 / 调整成员（超管）",
)
async def update_company_member(
    company_id: int,
    member_id: int,
    payload: CompanyMemberUpdateIn,
    db: DbSession,
    _: User = Depends(require_superadmin),
):
    return await company_service.update_member(
        db, company_id, member_id, role=payload.role, member_status=payload.status
    )
