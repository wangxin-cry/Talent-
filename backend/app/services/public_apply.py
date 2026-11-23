"""
公开招聘页与投递进度（PRD CE-01 / CE-02）

对外只暴露职位公开字段；投递后生成 tracking token，凭 token + 邮箱查询进度。
"""
from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import encrypt_pii, normalize_phone, sha256_hex
from app.core.storage import build_object_key, get_storage
from app.core.tenant import set_company_id
from app.models.application import (
    APP_HIRED,
    APP_INTERVIEW,
    APP_NEW,
    APP_OFFER,
    APP_REJECTED,
    APP_SCREENING,
    APP_STATUS_LABELS,
    Application,
    ApplicationStageHistory,
)
from app.models.base import utcnow
from app.models.candidate import RF_PENDING, Candidate, ResumeFile
from app.models.interview import ApplicationTracking, InterviewSchedule
from app.models.job import STATUS_PUBLISHED, Job
from app.services import company as company_service
from app.services import notifications as notification_svc
from app.services.audit import write_audit

PUBLIC_JOB_FIELDS = (
    Job.id,
    Job.title,
    Job.department,
    Job.location,
    Job.work_mode,
    Job.employment_type,
    Job.headcount,
    Job.education_level,
    Job.min_years,
    Job.salary_min,
    Job.salary_max,
    Job.description,
    Job.requirements,
    Job.published_at,
)

PROGRESS_ORDER = (APP_NEW, APP_SCREENING, APP_INTERVIEW, APP_OFFER, APP_HIRED)

# 候选人视角的阶段名称（内部状态名对外不友好）
PUBLIC_STEP_LABELS = {
    APP_NEW: "已投递",
    APP_SCREENING: "筛选中",
    APP_INTERVIEW: "面试中",
    APP_OFFER: "Offer 沟通",
    APP_HIRED: "已入职",
    APP_REJECTED: "流程结束",
}


def _job_row(row) -> dict:
    data = dict(row._mapping)
    if data.get("min_years") is not None:
        data["min_years"] = float(data["min_years"])
    return data


async def list_jobs(
    db: AsyncSession,
    *,
    company_slug: str,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    company = await company_service.get_by_slug(db, company_slug)
    conditions = [Job.status == STATUS_PUBLISHED, Job.company_id == company.id]
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(Job.title.ilike(like))

    total = int(
        (await db.execute(select(func.count()).select_from(Job).where(*conditions))).scalar_one()
    )
    rows = (
        await db.execute(
            select(*PUBLIC_JOB_FIELDS)
            .where(*conditions)
            .order_by(Job.published_at.desc().nullslast(), Job.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return [_job_row(row) for row in rows], total


async def get_job(db: AsyncSession, company_slug: str, job_id: int) -> dict:
    company = await company_service.get_by_slug(db, company_slug)
    row = (
        await db.execute(
            select(*PUBLIC_JOB_FIELDS).where(
                Job.id == job_id,
                Job.status == STATUS_PUBLISHED,
                Job.company_id == company.id,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="职位不存在或已下线")
    return _job_row(row)


async def _get_or_create_candidate(
    db: AsyncSession, name: str, email: str, phone: str | None, company_id: int
) -> Candidate:
    # 与手工建档保持同一套去重键：手机号优先，其次邮箱
    if phone:
        dedupe_key = f"phone:{sha256_hex(phone)}"
    elif email:
        dedupe_key = f"email:{sha256_hex(email)}"
    else:
        dedupe_key = f"public:{uuid.uuid4().hex}"

    candidate = (
        await db.execute(
            select(Candidate).where(
                Candidate.company_id == company_id,
                Candidate.dedupe_key == dedupe_key,
                Candidate.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if candidate is not None:
        return candidate

    candidate = Candidate(company_id=company_id, dedupe_key=dedupe_key, skills=[])
    candidate.name = name.strip()
    if phone:
        candidate.phone_enc = encrypt_pii(phone)
        candidate.phone_hash = sha256_hex(phone)
    candidate.email_enc = encrypt_pii(email)
    candidate.email_hash = sha256_hex(email)
    db.add(candidate)
    await db.flush()
    return candidate


async def _store_resume(
    db: AsyncSession, upload: UploadFile, candidate_id: int, job_id: int, company_id: int
) -> int | None:
    name = Path(upload.filename or "resume").name
    ext = Path(name).suffix.lower()
    data = await upload.read()
    if not data:
        return None
    if ext not in settings.allowed_ext_list:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的简历格式：{ext or '未知'}，请上传 PDF / DOCX / 图片",
        )
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"简历超过 {settings.MAX_UPLOAD_MB}MB，请压缩后重试",
        )

    sha = hashlib.sha256(data).hexdigest()
    file = (
        await db.execute(
            select(ResumeFile).where(
                ResumeFile.sha256 == sha, ResumeFile.company_id == company_id
            )
        )
    ).scalars().first()
    if file is not None:
        return file.id

    key = build_object_key(company_id, "resume", name)
    mime = upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    stored = get_storage().put(key, data, content_type=mime)
    file = ResumeFile(
        company_id=company_id,
        candidate_id=candidate_id,
        bucket=settings.MINIO_BUCKET,
        object_key=key,
        etag=str(stored.get("etag") or "")[:100],
        original_name=name,
        ext=ext,
        mime=mime,
        size_bytes=len(data),
        sha256=sha,
        source="public",
        applied_job_id=job_id,
        status=RF_PENDING,
    )
    db.add(file)
    await db.flush()
    return file.id


async def apply(
    db: AsyncSession,
    *,
    company_slug: str,
    job_id: int,
    name: str,
    email: str,
    phone: str | None,
    note: str | None = None,
    resume: UploadFile | None = None,
) -> tuple[Application, ApplicationTracking, int | None, str]:
    company = await company_service.get_by_slug(db, company_slug)
    job = await db.get(Job, job_id)
    if job is None or job.status != STATUS_PUBLISHED or job.company_id != company.id:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="职位不存在或已下线")
    # 公开接口无登录态，按职位所属公司建立租户上下文
    set_company_id(job.company_id)

    email = email.strip().lower()
    phone = normalize_phone(phone) if phone else None
    candidate = await _get_or_create_candidate(db, name, email, phone, job.company_id)

    application = (
        await db.execute(
            select(Application).where(
                Application.job_id == job.id, Application.candidate_id == candidate.id
            )
        )
    ).scalar_one_or_none()

    message = "投递成功，请保存查询凭证以跟踪进度"
    created = application is None
    if application is not None:
        message = "你已投递过该职位，可直接查询进度"
    else:
        now = utcnow()
        application = Application(
            job_id=job.id,
            candidate_id=candidate.id,
            status=APP_NEW,
            source="官网投递",
            applied_at=now,
            stage_entered_at=now,
            created_by=None,
            company_id=job.company_id,
        )
        db.add(application)
        await db.flush()
        db.add(
            ApplicationStageHistory(
                application_id=application.id,
                from_status=None,
                to_status=APP_NEW,
                operator_id=None,
                note=("官网投递" + (f"：{note}" if note else "")),
            )
        )
        job.apply_count = (job.apply_count or 0) + 1
        await notification_svc.create_notification(
            db,
            user_id=job.created_by,
            application_id=application.id,
            candidate_id=candidate.id,
            template="public_apply",
            subject="收到新的官网投递",
            body=f"{candidate.name or '候选人'} 通过招聘官网投递了「{job.title}」。",
        )

    tracking = (
        await db.execute(
            select(ApplicationTracking).where(ApplicationTracking.application_id == application.id)
        )
    ).scalar_one_or_none()
    if tracking is None:
        tracking = ApplicationTracking(
            company_id=job.company_id,
            application_id=application.id,
            email_hash=sha256_hex(email),
        )
        db.add(tracking)
    else:
        tracking.is_active = True

    file_id = None
    if resume is not None and resume.filename:
        file_id = await _store_resume(db, resume, candidate.id, job.id, job.company_id)

    await write_audit(
        db,
        action="public.apply",
        target_type="application",
        target_id=application.id,
        user_id=None,
        detail={"job_id": job.id, "source": "官网投递", "has_resume": file_id is not None},
    )
    await db.commit()
    await db.refresh(application)
    await db.refresh(tracking)
    if created:
        # 投递确认邮件（CE-03 / RA-01）
        await notification_svc.notify_candidate_status(db, application=application, to_status=APP_NEW)
    return application, tracking, file_id, message


async def get_progress(db: AsyncSession, token: str, email: str) -> dict:
    tracking = (
        await db.execute(
            select(ApplicationTracking).where(
                ApplicationTracking.token == token, ApplicationTracking.is_active.is_(True)
            )
        )
    ).scalar_one_or_none()
    if tracking is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="查询凭证无效")

    if tracking.email_hash != sha256_hex(email.strip().lower()):
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail="邮箱与投递记录不匹配")

    application = await db.get(Application, tracking.application_id)
    if application is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="投递记录不存在")

    job = await db.get(Job, application.job_id)
    candidate = await db.get(Candidate, application.candidate_id)
    history = (
        await db.execute(
            select(ApplicationStageHistory).where(
                ApplicationStageHistory.application_id == application.id
            )
        )
    ).scalars().all()
    reached_at = {
        item.to_status: item.create_time for item in history if item.to_status
    }

    current_index = PROGRESS_ORDER.index(application.status) if application.status in PROGRESS_ORDER else len(PROGRESS_ORDER)
    steps = []
    for index, stage in enumerate(PROGRESS_ORDER):
        steps.append(
            {
                "status": stage,
                "label": PUBLIC_STEP_LABELS.get(stage, APP_STATUS_LABELS.get(stage, stage)),
                "reached": index <= current_index,
                "current": application.status == stage,
                "time": reached_at.get(stage),
            }
        )

    message = None
    if application.status == APP_REJECTED:
        steps.append(
            {
                "status": APP_REJECTED,
                "label": "流程已结束",
                "reached": True,
                "current": True,
                "time": reached_at.get(APP_REJECTED),
            }
        )
        message = "感谢你的关注，本次流程已结束，欢迎关注其他在招职位。"

    schedule = (
        await db.execute(
            select(InterviewSchedule).where(InterviewSchedule.application_id == application.id)
        )
    ).scalar_one_or_none()

    tracking.last_viewed_at = utcnow()
    await db.commit()

    return {
        "job_title": job.title if job else "职位已下线",
        "candidate_name": candidate.name if candidate else None,
        "status": application.status,
        "status_label": PUBLIC_STEP_LABELS.get(
            application.status, APP_STATUS_LABELS.get(application.status, application.status)
        ),
        "applied_at": application.applied_at,
        "steps": steps,
        "interview_at": schedule.scheduled_at if schedule else None,
        "message": message,
    }
