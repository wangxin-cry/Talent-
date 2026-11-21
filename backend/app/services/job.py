"""
职位业务逻辑

- CRUD
- 状态机：draft → pending → published → closed → archived
- 发布前校验：描述、要求非空，技能 ≥ 1
- 实质修改 JD 时 jd_version + 1（匹配缓存依赖它）
"""
from __future__ import annotations

from fastapi import HTTPException, status as http_status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import utcnow
from app.models.job import (
    JD_SOURCE_AI,
    JD_SOURCE_MANUAL,
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_DRAFT,
    STATUS_PENDING,
    STATUS_PUBLISHED,
    Job,
)
from app.models.skill import Skill
from app.schemas.job import JobCreateIn, JobOut, SkillBrief, JobUpdateIn
from app.services.skills import ensure_skill_ids, load_skill_map

# 允许的状态流转
JOB_TRANSITIONS: dict[str, set[str]] = {
    STATUS_DRAFT: {STATUS_PENDING, STATUS_PUBLISHED, STATUS_ARCHIVED},
    STATUS_PENDING: {STATUS_PUBLISHED, STATUS_DRAFT},
    STATUS_PUBLISHED: {STATUS_CLOSED, STATUS_ARCHIVED},
    STATUS_CLOSED: {STATUS_ARCHIVED},
    STATUS_ARCHIVED: set(),
}

STATUS_LABELS = {
    STATUS_DRAFT: "草稿",
    STATUS_PENDING: "待审批",
    STATUS_PUBLISHED: "招聘中",
    STATUS_CLOSED: "已关闭",
    STATUS_ARCHIVED: "已归档",
}

JD_FIELDS = {"title", "description", "requirements", "skills", "must_have_skills"}

PUBLISH_REQUIRED = {
    "description": "职位描述",
    "requirements": "任职要求",
}


def _validate_publish(job: Job) -> None:
    """发布前校验，一次性返回所有缺失项"""
    missing: list[str] = []
    for field, label in PUBLISH_REQUIRED.items():
        if not (getattr(job, field) or "").strip():
            missing.append(label)
    if not (job.skills or []):
        missing.append("至少 1 个技能")
    if missing:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"发布前请补全：{'、'.join(missing)}",
        )


def job_to_out(job: Job, skill_map: dict[int, Skill]) -> JobOut:
    """把模型转成响应对象，技能 id 解析成名称"""
    def briefs(ids: list[int] | None) -> list[SkillBrief]:
        return [
            SkillBrief.model_validate(skill_map[skill_id])
            for skill_id in (ids or [])
            if skill_id in skill_map
        ]

    return JobOut(
        id=job.id,
        title=job.title,
        department=job.department,
        location=job.location,
        work_mode=job.work_mode,
        employment_type=job.employment_type,
        headcount=job.headcount,
        description=job.description,
        requirements=job.requirements,
        skills=briefs(job.skills),
        must_have_skills=briefs(job.must_have_skills),
        min_years=float(job.min_years) if job.min_years is not None else None,
        education_level=job.education_level,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        status=job.status,
        jd_source=job.jd_source,
        jd_version=job.jd_version,
        published_at=job.published_at,
        closed_at=job.closed_at,
        approved_by=job.approved_by,
        approved_at=job.approved_at,
        reject_reason=job.reject_reason,
        apply_count=job.apply_count,
        created_by=job.created_by,
        create_time=job.create_time,
        update_time=job.update_time,
    )


async def get_job_or_404(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="职位不存在"
        )
    return job


async def create_job(db: AsyncSession, data: JobCreateIn, user_id: int) -> Job:
    await ensure_skill_ids(db, [*data.skills, *data.must_have_skills])

    jd_source = JD_SOURCE_AI if data.jd_source == JD_SOURCE_AI else JD_SOURCE_MANUAL
    payload = data.model_dump(exclude={"jd_source"})
    job = Job(
        **payload,
        status=STATUS_DRAFT,
        jd_source=jd_source,
        created_by=user_id,
        company_id=1,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


async def update_job(db: AsyncSession, job: Job, data: JobUpdateIn) -> Job:
    changes = data.model_dump(exclude_unset=True)
    skills = changes.get("skills")
    must = changes.get("must_have_skills")
    if skills is not None or must is not None:
        await ensure_skill_ids(db, [*(skills or []), *(must or [])])

    jd_changed = any(
        field in changes and changes[field] != getattr(job, field) for field in JD_FIELDS
    )

    for field, value in changes.items():
        setattr(job, field, value)

    if jd_changed:
        job.jd_version += 1

    await db.commit()
    await db.refresh(job)
    return job


def _label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


async def change_status(db: AsyncSession, job: Job, target: str) -> Job:
    allowed = JOB_TRANSITIONS.get(job.status, set())
    if target not in allowed:
        allowed_text = "、".join(_label(s) for s in sorted(allowed)) or "无"
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"状态非法：{_label(job.status)} 不能直接转为 {_label(target)}；"
                f"当前允许：{allowed_text}"
            ),
        )

    if target == STATUS_PUBLISHED:
        _validate_publish(job)

    job.status = target
    if target == STATUS_PUBLISHED:
        job.published_at = utcnow()
    elif target == STATUS_CLOSED:
        job.closed_at = utcnow()

    await db.commit()
    await db.refresh(job)
    return job
def _mark_published(job: Job, reviewer_id: int) -> None:
    job.status = STATUS_PUBLISHED
    job.approved_by = reviewer_id
    job.approved_at = utcnow()
    job.published_at = utcnow()
    job.reject_reason = None

async def submit_for_approval(db: AsyncSession, job: Job) -> Job:
    """提交审批：只有草稿可提交，提交前先做发布校验"""
    if job.status != STATUS_DRAFT:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"只有草稿可以提交审批，当前状态：{_label(job.status)}",
        )
    _validate_publish(job)
    job.status = STATUS_PENDING
    job.reject_reason = None
    await db.commit()
    await db.refresh(job)
    return job

async def approve_job(db: AsyncSession, job: Job, reviewer_id: int) -> Job:
    """审批通过：pending → published，记录审批人"""
    if job.status != STATUS_PENDING:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"只有待审批职位可以审批，当前状态：{_label(job.status)}",
        )
    _validate_publish(job)
    _mark_published(job, reviewer_id)
    await db.commit()
    await db.refresh(job)
    return job

async def publish_job(db: AsyncSession, job: Job, reviewer_id: int) -> Job:
    """manager/admin 发布：草稿直发，或对待审批职位直接通过"""
    if job.status == STATUS_PENDING:
        return await approve_job(db, job, reviewer_id)
    if job.status != STATUS_DRAFT:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"状态非法：{_label(job.status)} 不能发布",
        )
    _validate_publish(job)
    _mark_published(job, reviewer_id)
    await db.commit()
    await db.refresh(job)
    return job

async def reject_job(db: AsyncSession, job: Job, reason: str) -> Job:
    """驳回：pending → draft，写入驳回原因，等待修改后重新提交"""
    if job.status != STATUS_PENDING:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"只有待审批职位可以驳回，当前状态：{_label(job.status)}",
        )
    job.status = STATUS_DRAFT
    job.reject_reason = reason.strip()
    job.approved_by = None
    job.approved_at = None
    await db.commit()
    await db.refresh(job)
    return job


async def list_jobs(
    db: AsyncSession,
    status: str | None = None,
    q: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[Job], int]:
    conditions = []
    if status:
        conditions.append(Job.status == status)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        conditions.append(or_(Job.title.ilike(keyword), Job.department.ilike(keyword)))

    base = select(Job)
    if conditions:
        base = base.where(*conditions)

    total = (
        await db.execute(select(func.count()).select_from(Job).where(*conditions))
    ).scalar_one()
    result = await db.execute(
        base.order_by(Job.update_time.desc(), Job.id.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all()), total


async def collect_skill_map(db: AsyncSession, jobs: list[Job]) -> dict[int, Skill]:
    ids: list[int] = []
    for job in jobs:
        ids.extend(job.skills or [])
        ids.extend(job.must_have_skills or [])
    return await load_skill_map(db, list(set(ids)))
