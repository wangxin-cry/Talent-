"""
技能词表服务

职责：
- 模糊搜索（名称 / 展示名 / 别名）
- 新建技能（同名或同别名视为已存在，直接返回）
- 把自由文本关键词归一为技能记录（K8s → Kubernetes）
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.skill import Skill


def _keys(skill: Skill) -> set[str]:
    keys = {skill.name.casefold()}
    if skill.display_name:
        keys.add(skill.display_name.casefold())
    keys.update(alias.casefold() for alias in (skill.aliases or []))
    return keys


async def _all_active(db: AsyncSession) -> list[Skill]:
    result = await db.execute(select(Skill).where(Skill.is_active.is_(True)))
    return list(result.scalars().all())


async def list_skills(db: AsyncSession, q: str | None = None, limit: int = 20) -> list[Skill]:
    """按关键字搜索技能；无关键字返回常用列表"""
    skills = await _all_active(db)
    skills.sort(key=lambda s: s.name.casefold())

    keyword = (q or "").strip().casefold()
    if keyword:
        matched = [
            skill
            for skill in skills
            if keyword in skill.name.casefold()
            or any(keyword in alias.casefold() for alias in (skill.aliases or []))
            or (skill.display_name and keyword in skill.display_name.casefold())
        ]
        return matched[:limit]
    return skills[:limit]


async def create_skill(
    db: AsyncSession,
    name: str,
    display_name: str | None = None,
    aliases: list[str] | None = None,
    category: str | None = None,
) -> Skill:
    """新建技能；若同名 / 同别名已存在则返回已有记录"""
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="技能名不能为空"
        )

    cleaned_aliases = list(dict.fromkeys(a.strip() for a in (aliases or []) if a.strip()))
    key = name.casefold()

    for skill in await _all_active(db):
        if key in _keys(skill):
            return skill

    skill = Skill(
        name=name,
        display_name=display_name.strip() if display_name else None,
        aliases=cleaned_aliases,
        category=category,
    )
    db.add(skill)
    await db.flush()
    return skill


async def resolve_skill_names(db: AsyncSession, names: list[str]) -> list[Skill]:
    """把关键词列表归一为技能记录；词表没有的按原词新建"""
    resolved: list[Skill] = []
    seen_ids: set[int] = set()
    skills = await _all_active(db)

    for raw in names:
        text = raw.strip()
        if not text:
            continue
        key = text.casefold()
        matched = next((skill for skill in skills if key in _keys(skill)), None)
        if matched is None:
            matched = Skill(name=text, aliases=[], category=None)
            db.add(matched)
            await db.flush()
            skills.append(matched)

        if matched.id not in seen_ids:
            seen_ids.add(matched.id)
            resolved.append(matched)

    return resolved


async def load_skill_map(db: AsyncSession, ids: list[int]) -> dict[int, Skill]:
    if not ids:
        return {}
    result = await db.execute(select(Skill).where(Skill.id.in_(set(ids))))
    return {skill.id: skill for skill in result.scalars().all()}


async def ensure_skill_ids(db: AsyncSession, ids: list[int]) -> None:
    """校验技能 id 都存在，否则 400"""
    if not ids:
        return
    found = await load_skill_map(db, ids)
    missing = [str(i) for i in ids if i not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"技能不存在：{', '.join(missing)}",
        )
