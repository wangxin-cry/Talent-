"""
数据范围（Data Scope）

约定：
- admin：全公司
- manager：已分配部门时 = 本部门职位 + 自己创建/审批的职位；未分配部门时 = 全公司
- recruiter：自己创建的职位 + 已发布职位（只读）；候选人 = 自己上传的 + 投递到可见职位的

所有查询列表都应带上对应的 scope condition；详情/写操作使用 ensure_* 校验。
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select

from app.models.application import Application
from app.models.candidate import Candidate
from app.models.job import STATUS_PUBLISHED, Job
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, User


def _same_company(model, user: User):
    """租户边界：所有业务查询的第一道条件"""
    return model.company_id == user.company_id


def job_scope_condition(user: User):
    """返回 SQLAlchemy 条件；None 表示不限制（仍在同公司内）"""
    base = _same_company(Job, user)
    if user.role == ROLE_ADMIN:
        return base
    if user.role == ROLE_MANAGER:
        if not user.department:
            return base
        return and_(
            base,
            or_(
                Job.department == user.department,
                Job.created_by == user.id,
                Job.approved_by == user.id,
            ),
        )
    return and_(base, or_(Job.created_by == user.id, Job.status == STATUS_PUBLISHED))


def candidate_scope_condition(user: User):
    base = _same_company(Candidate, user)
    if user.role == ROLE_ADMIN:
        return base
    job_condition = job_scope_condition(user)
    visible_job_ids = select(Job.id).where(job_condition)
    applied_candidate_ids = select(Application.candidate_id).where(
        Application.job_id.in_(visible_job_ids)
    )
    return and_(
        base,
        or_(
            Candidate.created_by == user.id,
            Candidate.id.in_(applied_candidate_ids),
        ),
    )


def application_scope_condition(user: User):
    base = _same_company(Application, user)
    job_condition = job_scope_condition(user)
    return and_(base, Application.job_id.in_(select(Job.id).where(job_condition)))


def _forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def can_read_job(user: User, job: Job) -> bool:
    if job.company_id != user.company_id:
        return False
    if user.role == ROLE_ADMIN:
        return True
    if user.role == ROLE_MANAGER:
        if not user.department:
            return True
        return (
            job.department == user.department
            or job.created_by == user.id
            or job.approved_by == user.id
        )
    return job.created_by == user.id or job.status == STATUS_PUBLISHED


def ensure_job_access(user: User, job: Job) -> None:
    if job.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    if not can_read_job(user, job):
        raise _forbidden("无权访问该职位")


def ensure_job_manage(user: User, job: Job) -> None:
    if job.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    if user.role == ROLE_ADMIN or job.created_by == user.id:
        return
    if user.role == ROLE_MANAGER and (
        not user.department or job.department == user.department
    ):
        return
    raise _forbidden("无权修改该职位")


def ensure_job_review(user: User, job: Job) -> None:
    if job.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    if user.role == ROLE_ADMIN or job.created_by == user.id:
        return
    if user.role == ROLE_MANAGER and (
        not user.department or job.department == user.department
    ):
        return
    raise _forbidden("无权审批该职位")


async def ensure_candidate_access(db, user: User, candidate: Candidate) -> None:
    if candidate.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="候选人不存在")
    if user.role == ROLE_ADMIN or candidate.created_by == user.id:
        return
    job_condition = job_scope_condition(user)
    visible_job_ids = select(Job.id).where(job_condition)
    applied = (
        await db.execute(
            select(Application.id)
            .where(
                Application.candidate_id == candidate.id,
                Application.job_id.in_(visible_job_ids),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if applied is None:
        raise _forbidden("无权访问该候选人")


async def ensure_application_access(db, user: User, application: Application) -> None:
    if application.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="投递不存在")
    job = await db.get(Job, application.job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="职位不存在")
    ensure_job_access(user, job)


async def ensure_file_access(db, user: User, file) -> None:
    """上传人本人 / admin 可访问；已归属候选人时还要过候选人数据范围"""
    if file.company_id != user.company_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="简历文件不存在")
    if user.role == ROLE_ADMIN or file.uploaded_by == user.id:
        return
    if file.candidate_id:
        candidate = await db.get(Candidate, file.candidate_id)
        if candidate is not None:
            await ensure_candidate_access(db, user, candidate)
            return
    raise _forbidden("无权访问该简历文件")
