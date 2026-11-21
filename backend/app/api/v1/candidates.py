"""
候选人接口

- POST /candidates/upload            多文件上传（MinIO + sha256 去重），后台解析
- GET  /candidates                   候选人列表（联系方式脱敏）
- POST /candidates                   手动新增
- GET  /candidates/{id}              详情（结构化结果 + 字段置信度）
- PUT  /candidates/{id}              校对保存
- GET  /resume-files/status          批量查询解析状态
- GET  /resume-files/{id}/download   预签名下载（10 分钟）+ 审计
- GET  /files/local/{key}            本地存储模式下的实际取文件路由（MinIO 模式不用）
- POST /resume-files/{id}/reparse    重新解析
"""
from __future__ import annotations

import mimetypes
from urllib.parse import quote

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Query,
    UploadFile,
    status,
)

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.storage import get_storage
from app.schemas.candidate import (
    CandidateCreateIn,
    CandidateDetailOut,
    CandidateListOut,
    CandidateUpdateIn,
    DownloadOut,
    FileStatusListOut,
    UploadItemOut,
    UploadOut,
)
from app.services import audit
from app.services import candidates as candidate_service
from app.services.candidates import run_parse_task

router = APIRouter(tags=["候选人"])

@router.post(
    "/candidates/upload",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    summary="上传简历（多文件）",
)
async def upload_api(
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
    files: list[UploadFile] = File(...),
    applied_job_id: int | None = Form(default=None),
) -> UploadOut:
    if not files:
        raise_400("请至少选择一个文件")
    if len(files) > settings.RESUME_MAX_FILES:
        raise_400(f"一次最多上传 {settings.RESUME_MAX_FILES} 个文件")

    items = await candidate_service.upload_files(db, files, user.id, applied_job_id)
    for item in items:
        if item["file_id"] and not item["reused"] and item["status"] == "pending":
            background.add_task(run_parse_task, item["file_id"])
    return UploadOut(items=[UploadItemOut(**item) for item in items])

def raise_400(message: str) -> None:
    from fastapi import HTTPException

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)

@router.get("/candidates", response_model=CandidateListOut, summary="候选人列表")
async def list_api(
    db: DbSession,
    _: CurrentUser,
    q: str | None = Query(default=None, max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> CandidateListOut:
    items, total = await candidate_service.list_candidates(
        db, q=q, skip=(page - 1) * page_size, limit=page_size
    )
    return CandidateListOut(items=items, total=total)

@router.post(
    "/candidates",
    response_model=CandidateDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="手动新增候选人",
)
async def create_api(data: CandidateCreateIn, db: DbSession, user: CurrentUser) -> CandidateDetailOut:
    return await candidate_service.create_candidate(db, data, user.id)

@router.get("/candidates/{candidate_id}", response_model=CandidateDetailOut, summary="候选人详情")
async def detail_api(candidate_id: int, db: DbSession, _: CurrentUser) -> CandidateDetailOut:
    return await candidate_service.get_candidate_detail(db, candidate_id)

@router.put("/candidates/{candidate_id}", response_model=CandidateDetailOut, summary="校对保存")
async def update_api(
    candidate_id: int,
    data: CandidateUpdateIn,
    db: DbSession,
    user: CurrentUser,
) -> CandidateDetailOut:
    return await candidate_service.update_candidate(db, candidate_id, data, user.id)

@router.get("/resume-files/status", response_model=FileStatusListOut, summary="批量查询解析状态")
async def status_api(
    db: DbSession,
    _: CurrentUser,
    ids: str = Query(description="逗号分隔的文件 id"),
) -> FileStatusListOut:
    id_list = [int(part) for part in ids.split(",") if part.strip().isdigit()]
    return FileStatusListOut(items=await candidate_service.file_statuses(db, id_list[:50]))

@router.get("/resume-files/{file_id}/download", response_model=DownloadOut, summary="下载简历（预签名）")
async def download_api(file_id: int, db: DbSession, user: CurrentUser) -> DownloadOut:
    file = await candidate_service.get_file_or_404(db, file_id)
    url = get_storage().presign_get(file.object_key, settings.PRESIGN_EXPIRE_SECONDS)
    await audit.write_audit(
        db, action="resume.download", target_type="resume_file",
        target_id=file.id, user_id=user.id,
        detail={"candidate_id": file.candidate_id, "original_name": file.original_name},
    )
    await db.commit()
    return DownloadOut(
        url=url,
        expires_in=settings.PRESIGN_EXPIRE_SECONDS,
        filename=file.original_name,
    )

@router.post("/resume-files/{file_id}/reparse", response_model=UploadItemOut, summary="重新解析")
async def reparse_api(
    file_id: int,
    background: BackgroundTasks,
    db: DbSession,
    user: CurrentUser,
) -> UploadItemOut:
    file = await candidate_service.reparse_file(db, file_id, user.id)
    background.add_task(run_parse_task, file.id)
    return UploadItemOut(
        file_id=file.id,
        original_name=file.original_name,
        size_bytes=file.size_bytes,
        sha256=file.sha256,
        reused=False,
        status=file.status,
        candidate_id=file.candidate_id,
        message="已重新提交解析",
    )


@router.get(
    "/files/local/{object_key:path}",
    summary="本地存储模式下的文件下载",
    include_in_schema=False,
)
async def download_local(
    object_key: str,
    db: DbSession,
    _: CurrentUser,
):
    """
    本地磁盘存储（STORAGE_BACKEND=local）时的实际取文件入口。

    MinIO 模式返回的是对象存储预签名 URL，不会走到这里；
    该路由保留时也仅在 local 模式下生效，避免多一个未授权的取文件通道。
    """
    from fastapi import HTTPException
    from fastapi.responses import Response

    if settings.STORAGE_BACKEND.lower() != "local":
        raise HTTPException(status_code=404, detail="该地址仅在本地存储模式可用")

    storage = get_storage()
    if not storage.exists(object_key):
        raise HTTPException(status_code=404, detail="文件不存在")

    data = storage.get(object_key)
    media_type = mimetypes.guess_type(object_key)[0] or "application/octet-stream"
    filename = quote(object_key.rsplit("/", 1)[-1])
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )