"""公开招聘页 / 投递 / 进度查询（CE-01、CE-02），无需登录"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status

from app.core.deps import DbSession
from app.schemas.interview import (
    ApplyResultOut,
    ProgressOut,
    PublicJobListOut,
    PublicJobOut,
)
from app.services import public_apply
from app.services.queue import enqueue_parse_resume

router = APIRouter(prefix="/public", tags=["公开招聘页"])


@router.get("/jobs", response_model=PublicJobListOut, summary="在招职位列表")
async def list_public_jobs(
    db: DbSession,
    slug: str = Query(..., max_length=40, description="公司标识，来自 /careers/{slug}"),
    keyword: str | None = Query(default=None, max_length=50),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
) -> PublicJobListOut:
    items, total = await public_apply.list_jobs(
        db, company_slug=slug, keyword=keyword, page=page, page_size=page_size
    )
    return PublicJobListOut(total=total, items=[PublicJobOut(**item) for item in items])


@router.get("/jobs/{job_id}", response_model=PublicJobOut, summary="职位详情")
async def public_job_detail(
    job_id: int, db: DbSession, slug: str = Query(..., max_length=40)
) -> PublicJobOut:
    return PublicJobOut(**await public_apply.get_job(db, slug, job_id))


@router.post(
    "/applications",
    response_model=ApplyResultOut,
    status_code=status.HTTP_201_CREATED,
    summary="官网投递（可选上传简历）",
)
async def public_apply_api(
    db: DbSession,
    background: BackgroundTasks,
    company_slug: str = Form(..., max_length=40),
    job_id: int = Form(...),
    name: str = Form(..., min_length=2, max_length=50),
    email: str = Form(..., max_length=255),
    phone: str | None = Form(default=None, max_length=30),
    note: str | None = Form(default=None, max_length=500),
    resume: UploadFile | None = File(default=None),
) -> ApplyResultOut:
    application, tracking, file_id, message = await public_apply.apply(
        db,
        company_slug=company_slug,
        job_id=job_id,
        name=name,
        email=email,
        phone=phone,
        note=note,
        resume=resume,
    )
    if file_id is not None:
        enqueue_parse_resume(background, file_id)
    job = await public_apply.get_job(db, company_slug, application.job_id)
    return ApplyResultOut(
        application_id=application.id,
        tracking_token=tracking.token,
        job_title=job["title"],
        message=message,
    )


@router.get("/applications/status", response_model=ProgressOut, summary="查询投递进度")
async def progress_api(
    db: DbSession,
    token: str = Query(..., min_length=8, max_length=64),
    email: str = Query(..., max_length=255),
) -> ProgressOut:
    return ProgressOut(**await public_apply.get_progress(db, token, email))
