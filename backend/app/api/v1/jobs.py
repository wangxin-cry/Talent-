"""
职位接口

前缀：/api/v1/jobs
- 三角色均可管理职位（权限矩阵：职位管理 ✅ recruiter / manager / admin）
- 状态流转：publish / close / archive
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, DbSession
from app.models.job import STATUS_ARCHIVED, STATUS_CLOSED, STATUS_PUBLISHED
from app.schemas.job import (
    JDGenerateIn,
    JDGenerateOut,
    JobCreateIn,
    JobRejectIn,
    JobListOut,
    JobOut,
    JobUpdateIn,
)
from app.services import job as job_service
from app.services.jd_writer import generate_jd
from app.services.job import STATUS_LABELS
from app.services.skills import load_skill_map

REVIEW_ROLES = {"manager", "admin"}

router = APIRouter(prefix="/jobs", tags=["职位"])

def _require_reviewer(user) -> None:
    if user.role not in REVIEW_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有用人经理或管理员可以审批职位",
        )

async def _to_out(db: AsyncSession, job) -> JobOut:
    skill_map = await load_skill_map(
        db, list(set([*(job.skills or []), *(job.must_have_skills or [])]))
    )
    return job_service.job_to_out(job, skill_map)


@router.post("/generate-jd", response_model=JDGenerateOut, summary="AI 生成 JD")
async def generate_jd_api(data: JDGenerateIn, db: DbSession, _: CurrentUser) -> JDGenerateOut:
    result = await generate_jd(db, data)
    # 生成过程中可能按关键词新建技能，必须提交；否则返回的 skill id 会随会话回滚而失效
    await db.commit()
    return result


@router.get("", response_model=JobListOut, summary="职位列表")
async def list_jobs_api(
    db: DbSession,
    _: CurrentUser,
    status_filter: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JobListOut:
    if status_filter and status_filter not in STATUS_LABELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="无效的职位状态"
        )

    jobs, total = await job_service.list_jobs(
        db,
        status=status_filter,
        q=q,
        skip=(page - 1) * page_size,
        limit=page_size,
    )
    skill_map = await job_service.collect_skill_map(db, jobs)
    return JobListOut(
        items=[job_service.job_to_out(job, skill_map) for job in jobs],
        total=total,
    )


@router.post("", response_model=JobOut, status_code=status.HTTP_201_CREATED, summary="创建职位")
async def create_job_api(data: JobCreateIn, db: DbSession, user: CurrentUser) -> JobOut:
    job = await job_service.create_job(db, data, user.id)
    return await _to_out(db, job)


@router.get("/{job_id}", response_model=JobOut, summary="职位详情")
async def get_job_api(job_id: int, db: DbSession, _: CurrentUser) -> JobOut:
    job = await job_service.get_job_or_404(db, job_id)
    return await _to_out(db, job)


@router.put("/{job_id}", response_model=JobOut, summary="编辑职位")
async def update_job_api(
    job_id: int, data: JobUpdateIn, db: DbSession, _: CurrentUser
) -> JobOut:
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.update_job(db, job, data)
    return await _to_out(db, job)


@router.post("/{job_id}/publish", response_model=JobOut, summary="发布职位（manager/admin）")
async def publish_job_api(job_id: int, db: DbSession, user: CurrentUser) -> JobOut:
    if user.role not in REVIEW_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="招聘专员不能直接发布职位，请先提交审批",
        )
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.publish_job(db, job, user.id)
    return await _to_out(db, job)

@router.post("/{job_id}/submit", response_model=JobOut, summary="提交审批")
async def submit_job_api(job_id: int, db: DbSession, _: CurrentUser) -> JobOut:
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.submit_for_approval(db, job)
    return await _to_out(db, job)

@router.post("/{job_id}/approve", response_model=JobOut, summary="审批通过")
async def approve_job_api(job_id: int, db: DbSession, user: CurrentUser) -> JobOut:
    _require_reviewer(user)
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.approve_job(db, job, user.id)
    return await _to_out(db, job)

@router.post("/{job_id}/reject", response_model=JobOut, summary="驳回职位")
async def reject_job_api(
    job_id: int, data: JobRejectIn, db: DbSession, user: CurrentUser
) -> JobOut:
    _require_reviewer(user)
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.reject_job(db, job, data.reason)
    return await _to_out(db, job)


@router.post("/{job_id}/close", response_model=JobOut, summary="关闭职位")
async def close_job_api(job_id: int, db: DbSession, _: CurrentUser) -> JobOut:
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.change_status(db, job, STATUS_CLOSED)
    return await _to_out(db, job)


@router.post("/{job_id}/archive", response_model=JobOut, summary="归档职位")
async def archive_job_api(job_id: int, db: DbSession, _: CurrentUser) -> JobOut:
    job = await job_service.get_job_or_404(db, job_id)
    job = await job_service.change_status(db, job, STATUS_ARCHIVED)
    return await _to_out(db, job)
