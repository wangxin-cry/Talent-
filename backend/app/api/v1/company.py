"""公司信息与成员管理（公司管理员）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession, require_admin
from app.models.company import Company
from app.models.user import ROLE_ADMIN, User
from app.schemas.company import (
    CompanyCurrentOut,
    CompanyLookupOut,
    CompanyMemberOut,
    CompanyMemberUpdateIn,
)
from app.services import company as company_service

router = APIRouter(prefix="/company", tags=["公司"])


@router.get("/lookup", response_model=CompanyLookupOut, summary="按邀请码查询公司（注册页）")
async def lookup_company(
    db: DbSession, invite_code: str = Query(min_length=4, max_length=16)
) -> CompanyLookupOut:
    company = await company_service.lookup_by_invite(db, invite_code)
    return CompanyLookupOut(name=company.name, slug=company.slug)


@router.get("/current", response_model=CompanyCurrentOut, summary="当前公司信息")
async def current_company(user: CurrentUser, db: DbSession) -> CompanyCurrentOut:
    if user.company_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前账号不属于任何公司")
    company = await db.get(Company, user.company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="公司不存在")
    member_count = (
        await db.execute(
            select(func.count()).select_from(User).where(User.company_id == company.id)
        )
    ).scalar_one()
    return CompanyCurrentOut(
        id=company.id,
        name=company.name,
        slug=company.slug,
        status=company.status,
        invite_code=company.invite_code if user.role == ROLE_ADMIN else None,
        member_count=int(member_count),
    )


@router.post(
    "/invite/reset",
    response_model=CompanyCurrentOut,
    summary="重置邀请码（管理员）",
)
async def reset_invite_code(
    db: DbSession, user: User = Depends(require_admin)
) -> CompanyCurrentOut:
    company = await company_service.reset_invite_code(db, user.company_id)
    return CompanyCurrentOut(
        id=company.id,
        name=company.name,
        slug=company.slug,
        status=company.status,
        invite_code=company.invite_code,
    )


@router.get(
    "/members", response_model=list[CompanyMemberOut], summary="公司成员列表（管理员）"
)
async def list_members(db: DbSession, user: User = Depends(require_admin)):
    return await company_service.list_members(db, user.company_id)


@router.patch(
    "/members/{member_id}",
    response_model=CompanyMemberOut,
    summary="调整成员角色 / 启用停用（管理员）",
)
async def update_member(
    member_id: int,
    payload: CompanyMemberUpdateIn,
    db: DbSession,
    user: User = Depends(require_admin),
) -> CompanyMemberOut:
    if member_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="不能修改自己的角色或状态")
    member = await company_service.update_member(
        db, user.company_id, member_id, role=payload.role, member_status=payload.status
    )
    return member
