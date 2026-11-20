"""
技能词表接口

前缀：/api/v1/skills
"""
from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.job import SkillCreateIn, SkillOut
from app.services.skills import create_skill, list_skills

router = APIRouter(prefix="/skills", tags=["技能"])


@router.get("", response_model=list[SkillOut], summary="搜索技能")
async def search_skills_api(
    db: DbSession,
    _: CurrentUser,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[SkillOut]:
    skills = await list_skills(db, q=q, limit=limit)
    return [SkillOut.model_validate(skill) for skill in skills]


@router.post(
    "", response_model=SkillOut, status_code=status.HTTP_201_CREATED, summary="新建技能"
)
async def create_skill_api(data: SkillCreateIn, db: DbSession, _: CurrentUser) -> SkillOut:
    skill = await create_skill(
        db,
        name=data.name,
        display_name=data.display_name,
        aliases=data.aliases,
        category=data.category,
    )
    await db.commit()
    await db.refresh(skill)
    return SkillOut.model_validate(skill)
