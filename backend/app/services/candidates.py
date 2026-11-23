"""
候选人业务逻辑（阶段四）

- 上传：类型/大小校验 → sha256 命中复用 → 存对象存储 → 写 resume_file
- 解析：PDF(pdfplumber→PyMuPDF) / DOCX / 图片视觉 → LLM 抽取 → 结构化
- 去重：手机号 → 邮箱 → 文件 sha256 三级 dedupe_key，同人合并
- 兜底：解析失败只改状态不抛 500，提示手动录入
"""
from __future__ import annotations

import hashlib
import mimetypes
import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException, UploadFile, status as http_status
from loguru import logger
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import decrypt_pii, encrypt_pii, normalize_phone, sha256_hex
from app.core.storage import build_object_key, get_storage
from app.core.tenant import get_company_id, require_company_id, set_company_id
from app.models.application import (
    APP_STATUS_LABELS,
    Application,
    ApplicationStageHistory,
)
from app.models.base import utcnow
from app.models.candidate import (
    RF_FAILED,
    RF_PARSING,
    RF_PENDING,
    RF_SUCCESS,
    Candidate,
    Resume,
    ResumeFile,
)
from app.models.interview_question import InterviewQuestion
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.user import ROLE_ADMIN, ROLE_MANAGER
from app.schemas.candidate import (
    CandidateApplicationOut,
    CandidateCreateIn,
    CandidateDetailOut,
    CandidateMatchOut,
    CandidateOut,
    CandidateOverviewOut,
    CandidateTimelineItemOut,
    CandidateUpdateIn,
    FileStatusOut,
    ResumeFileOut,
)
from app.services import audit, scope, vision
from app.services import notifications as notification_svc
from app.services.parser import ParseError, ensure_quality, extract_text, render_pdf_images
from app.services.resume_extract import extract_resume

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

EDU_LEVELS = (
    ("博士", "phd"),
    ("硕士", "master"),
    ("研究生", "master"),
    ("本科", "bachelor"),
    ("学士", "bachelor"),
    ("大专", "college"),
    ("专科", "college"),
)

# ---------------------------------------------------------------- 工具
def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return phone if len(phone) < 7 else f"{phone[:3]}****{phone[-4:]}"

def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    head = name[:2] if len(name) > 2 else name[:1]
    return f"{head}***@{domain}"

def _edu_level(value: str | None) -> str | None:
    if not value:
        return None
    for keyword, level in EDU_LEVELS:
        if keyword in value:
            return level
    return value[:20]

def _clean_skills(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = (value or "").strip()
        if text and text not in result:
            result.append(text)
    return result[:100]

def _dedupe_key(phone: str | None, email: str | None, fallback: str) -> str:
    if phone and len(phone) >= 7:
        return f"phone:{sha256_hex(phone)}"
    if email and "@" in email:
        return f"email:{sha256_hex(email)}"
    return fallback

def _item(
    name: str,
    size: int,
    sha: str | None,
    reused: bool,
    file_status: str,
    candidate_id: int | None = None,
    message: str | None = None,
    file_id: int | None = None,
) -> dict:
    return {
        "file_id": file_id,
        "original_name": name,
        "size_bytes": size,
        "sha256": sha,
        "reused": reused,
        "status": file_status,
        "candidate_id": candidate_id,
        "message": message,
    }

# ---------------------------------------------------------------- 查询
async def get_candidate_or_404(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = await db.get(Candidate, candidate_id)
    company_id = get_company_id()
    if (
        candidate is None
        or candidate.is_deleted
        or (company_id is not None and candidate.company_id != company_id)
    ):
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="候选人不存在")
    return candidate

async def get_file_or_404(db: AsyncSession, file_id: int) -> ResumeFile:
    file = await db.get(ResumeFile, file_id)
    company_id = get_company_id()
    if file is None or (company_id is not None and file.company_id != company_id):
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="简历文件不存在")
    return file

async def _file_overview(db: AsyncSession, candidate_ids: list[int]) -> dict[int, dict]:
    if not candidate_ids:
        return {}
    result = await db.execute(
        select(ResumeFile)
        .where(ResumeFile.candidate_id.in_(candidate_ids))
        .order_by(ResumeFile.create_time.desc(), ResumeFile.id.desc())
    )
    overview: dict[int, dict] = {cid: {"count": 0, "latest": None} for cid in candidate_ids}
    for file in result.scalars().all():
        item = overview.setdefault(file.candidate_id, {"count": 0, "latest": None})
        item["count"] += 1
        if item["latest"] is None:
            item["latest"] = file.status
    return overview

def _to_out(candidate: Candidate, overview: dict | None = None, masked: bool = True) -> CandidateOut:
    info = (overview or {}).get(candidate.id, {})
    phone = decrypt_pii(candidate.phone_enc)
    email = decrypt_pii(candidate.email_enc)
    return CandidateOut(
        id=candidate.id,
        name=candidate.name,
        phone=_mask_phone(phone) if masked else phone,
        email=_mask_email(email) if masked else email,
        city=candidate.city,
        education_level=candidate.education_level,
        school=candidate.school,
        major=candidate.major,
        years_experience=float(candidate.years_experience) if candidate.years_experience is not None else None,
        current_company=candidate.current_company,
        current_title=candidate.current_title,
        skills=list(candidate.skills or []),
        file_count=int(info.get("count") or 0),
        latest_status=info.get("latest"),
        create_time=candidate.create_time,
        update_time=candidate.update_time,
    )

async def list_candidates(
    db: AsyncSession,
    q: str | None = None,
    skip: int = 0,
    limit: int = 20,
    scope=None,
) -> tuple[list[CandidateOut], int]:
    conditions = [Candidate.is_deleted.is_(False)]
    if scope is not None:
        conditions.append(scope)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        conditions.append(or_(
            Candidate.name.ilike(keyword),
            Candidate.school.ilike(keyword),
            Candidate.current_company.ilike(keyword),
            Candidate.current_title.ilike(keyword),
        ))

    total = (await db.execute(
        select(func.count()).select_from(Candidate).where(*conditions)
    )).scalar_one()
    rows = (await db.execute(
        select(Candidate)
        .where(*conditions)
        .order_by(Candidate.update_time.desc(), Candidate.id.desc())
        .offset(skip)
        .limit(limit)
    )).scalars().all()

    overview = await _file_overview(db, [row.id for row in rows])
    return [_to_out(row, overview, masked=True) for row in rows], total

async def get_candidate_detail(db: AsyncSession, candidate_id: int) -> CandidateDetailOut:
    candidate = await get_candidate_or_404(db, candidate_id)
    files = list((await db.execute(
        select(ResumeFile)
        .where(ResumeFile.candidate_id == candidate.id)
        .order_by(ResumeFile.create_time.desc(), ResumeFile.id.desc())
    )).scalars().all())
    overview = {candidate.id: {"count": len(files), "latest": files[0].status if files else None}}
    base = _to_out(candidate, overview, masked=False)

    resume = (await db.execute(
        select(Resume)
        .where(Resume.candidate_id == candidate.id)
        .order_by(Resume.version.desc(), Resume.id.desc())
        .limit(1)
    )).scalars().first()

    return CandidateDetailOut(
        **base.model_dump(),
        files=[ResumeFileOut.model_validate(file) for file in files],
        resume_id=resume.id if resume else None,
        structured=resume.structured if resume else None,
        field_confidence=resume.field_confidence if resume else {},
        plain_text=resume.plain_text if resume else None,
        parser_meta=resume.parser_meta if resume else {},
    )

async def file_statuses(db: AsyncSession, ids: list[int]) -> list[FileStatusOut]:
    if not ids:
        return []
    rows = (await db.execute(
        select(ResumeFile).where(
            ResumeFile.id.in_(ids),
            ResumeFile.company_id == require_company_id(),
        )
    )).scalars().all()
    return [
        FileStatusOut(
            id=row.id,
            status=row.status,
            error_reason=row.error_reason,
            candidate_id=row.candidate_id,
        )
        for row in rows
    ]

# ---------------------------------------------------------------- 手工建档 / 校对
async def create_candidate(db: AsyncSession, data: CandidateCreateIn, user_id: int) -> CandidateDetailOut:
    company_id = require_company_id()
    phone = normalize_phone(data.phone)
    email = (data.email or "").strip().lower() or None
    key = _dedupe_key(phone, email, f"manual:{uuid.uuid4().hex}")

    existing = (await db.execute(
        select(Candidate).where(
            Candidate.company_id == company_id,
            Candidate.dedupe_key == key,
            Candidate.is_deleted.is_(False),
        )
    )).scalars().first()
    if existing is not None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="该手机号 / 邮箱已存在候选人，请直接校对已有记录",
        )

    candidate = Candidate(company_id=company_id, dedupe_key=key, created_by=user_id, skills=[])
    candidate.name = data.name.strip()
    if phone:
        candidate.phone_enc = encrypt_pii(phone)
        candidate.phone_hash = sha256_hex(phone)
    if email:
        candidate.email_enc = encrypt_pii(email)
        candidate.email_hash = sha256_hex(email)
    candidate.city = data.city
    candidate.education_level = _edu_level(data.education_level)
    candidate.school = data.school
    candidate.major = data.major
    candidate.current_company = data.current_company
    candidate.current_title = data.current_title
    candidate.years_experience = (
        Decimal(str(round(data.years_experience, 1))) if data.years_experience is not None else None
    )
    candidate.skills = _clean_skills(data.skills)

    db.add(candidate)
    await db.flush()
    await audit.write_audit(
        db, action="candidate.create", target_type="candidate",
        target_id=candidate.id, user_id=user_id, detail={"source": "manual"},
    )
    await notification_svc.notify_roles(
        db,
        roles={ROLE_MANAGER, ROLE_ADMIN},
        exclude_user_ids={user_id},
        template="candidate_created",
        subject="新增候选人",
        body=f"候选人「{candidate.name}」已手工录入人才库。",
        candidate_id=candidate.id,
    )
    await db.commit()
    return await get_candidate_detail(db, candidate.id)

async def update_candidate(
    db: AsyncSession,
    candidate_id: int,
    data: CandidateUpdateIn,
    user_id: int,
) -> CandidateDetailOut:
    candidate = await get_candidate_or_404(db, candidate_id)
    changes = data.model_dump(exclude_unset=True)
    touched = sorted(changes.keys())

    if "name" in changes:
        name = (changes.pop("name") or "").strip()
        if not name:
            raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="姓名不能为空")
        candidate.name = name

    phone_changed = "phone" in changes
    email_changed = "email" in changes
    if phone_changed:
        phone = normalize_phone(changes.pop("phone"))
        candidate.phone_enc = encrypt_pii(phone) if phone else None
        candidate.phone_hash = sha256_hex(phone) if phone else None
    if email_changed:
        email = (changes.pop("email") or "").strip().lower() or None
        candidate.email_enc = encrypt_pii(email) if email else None
        candidate.email_hash = sha256_hex(email) if email else None

    if phone_changed or email_changed:
        phone = decrypt_pii(candidate.phone_enc)
        email = decrypt_pii(candidate.email_enc)
        key = _dedupe_key(normalize_phone(phone), email, f"manual:{candidate.id}")
        if key != candidate.dedupe_key:
            conflict = (await db.execute(
                select(Candidate).where(
                    Candidate.company_id == candidate.company_id,
                    Candidate.dedupe_key == key,
                    Candidate.id != candidate.id,
                )
            )).scalars().first()
            if conflict is not None:
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail="该手机号 / 邮箱已属于其他候选人",
                )
            candidate.dedupe_key = key

    for field in ("city", "school", "major", "current_company", "current_title"):
        if field in changes:
            value = changes.pop(field)
            setattr(candidate, field, (value or "").strip() or None)
    if "education_level" in changes:
        candidate.education_level = _edu_level(changes.pop("education_level"))
    if "years_experience" in changes:
        value = changes.pop("years_experience")
        candidate.years_experience = (
            Decimal(str(round(float(value), 1))) if value is not None else None
        )
    if "skills" in changes:
        candidate.skills = _clean_skills(changes.pop("skills"))

    await audit.write_audit(
        db, action="candidate.update", target_type="candidate",
        target_id=candidate.id, user_id=user_id, detail={"fields": touched},
    )
    await db.commit()
    return await get_candidate_detail(db, candidate.id)

# ---------------------------------------------------------------- 上传
async def upload_files(
    db: AsyncSession,
    uploads: list[UploadFile],
    user_id: int,
    applied_job_id: int | None = None,
    max_file_mb: int | None = None,
) -> list[dict]:
    items: list[dict] = []
    company_id = require_company_id()
    storage = get_storage()
    allowed = settings.allowed_ext_list
    limit_mb = max_file_mb or settings.MAX_UPLOAD_MB
    limit_bytes = limit_mb * 1024 * 1024

    for upload in uploads:
        name = Path(upload.filename or "resume").name
        ext = Path(name).suffix.lower()
        data = await upload.read()
        size = len(data)

        if ext not in allowed:
            items.append(_item(
                name, size, None, False, RF_FAILED,
                message=f"不支持的格式：{ext or '未知'}，请上传 PDF / DOCX / 图片",
            ))
            continue
        if size == 0:
            items.append(_item(name, 0, None, False, RF_FAILED, message="文件为空，请重新上传"))
            continue
        if size > limit_bytes:
            items.append(_item(
                name, size, None, False, RF_FAILED,
                message=f"文件超过 {limit_mb}MB，请压缩后重试",
            ))
            continue

        sha = hashlib.sha256(data).hexdigest()
        existing = (await db.execute(
            select(ResumeFile).where(
                ResumeFile.sha256 == sha, ResumeFile.company_id == company_id
            )
        )).scalars().first()
        if existing is not None:
            items.append(_item(
                existing.original_name, existing.size_bytes, sha, True, existing.status,
                existing.candidate_id,
                "文件已存在，复用已有解析结果" if existing.status == RF_SUCCESS else "文件已存在，沿用当前解析状态",
                existing.id,
            ))
            continue

        key = build_object_key(company_id, "resume", name)
        mime = upload.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        try:
            stored = storage.put(key, data, content_type=mime)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"简历写入对象存储失败 | {name} | {exc}")
            items.append(_item(name, size, sha, False, RF_FAILED, message="文件存储失败，请稍后重试"))
            continue

        file = ResumeFile(
            company_id=company_id,
            bucket=settings.MINIO_BUCKET,
            object_key=key,
            etag=str(stored.get("etag") or "")[:100],
            original_name=name,
            ext=ext,
            mime=mime,
            size_bytes=size,
            sha256=sha,
            source="upload",
            applied_job_id=applied_job_id,
            status=RF_PENDING,
            uploaded_by=user_id,
        )

        try:
            # savepoint：并发上传同一文件时只回滚这一行，不影响整批
            async with db.begin_nested():
                db.add(file)
                await db.flush()
        except IntegrityError:
            existing = (await db.execute(
                select(ResumeFile).where(
                    ResumeFile.sha256 == sha, ResumeFile.company_id == company_id
                )
            )).scalars().first()
            if existing is not None:
                items.append(_item(
                    existing.original_name, existing.size_bytes, sha, True, existing.status,
                    existing.candidate_id, "文件已存在，复用已有记录", existing.id,
                ))
                continue
            logger.warning(f"简历入库冲突且未查到同公司记录 | sha={sha} | company={company_id}")
            items.append(_item(name, size, sha, False, RF_FAILED, message="文件登记冲突，请稍后重试"))
            continue

        await audit.write_audit(
            db, action="resume.upload", target_type="resume_file",
            target_id=file.id, user_id=user_id,
            detail={
                "original_name": name,
                "size_bytes": size,
                "sha256": sha,
                "applied_job_id": applied_job_id,
            },
        )
        items.append(_item(name, size, sha, False, RF_PENDING, None, None, file.id))

    await db.commit()
    return items

# ---------------------------------------------------------------- 后台解析
async def run_parse_task(file_id: int, trace_id: str | None = None) -> None:
    """BackgroundTasks 入口：独立会话，异常不影响接口响应"""
    async with SessionLocal() as db:
        try:
            await process_file(db, file_id, trace_id=trace_id)
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            logger.exception(f"简历解析异常 | file_id={file_id} | {exc}")
            await _mark_failed(db, file_id, "解析失败，请手动录入或稍后重试")

async def _mark_failed(db: AsyncSession, file_id: int, reason: str) -> None:
    file = await db.get(ResumeFile, file_id)
    if file is None:
        return
    # 解析在后台/worker 中执行，需要显式恢复公司上下文（AI 成本、审计、索引都依赖）
    set_company_id(file.company_id)
    file.status = RF_FAILED
    file.error_reason = reason[:500]
    file.parsed_time = utcnow()
    await audit.write_audit(
        db, action="resume.parse_failed", target_type="resume_file",
        target_id=file.id, user_id=file.uploaded_by, detail={"reason": reason[:500]},
    )
    await notification_svc.create_notification(
        db,
        user_id=file.uploaded_by,
        candidate_id=file.candidate_id,
        template="resume_parse_failed",
        subject="简历解析失败",
        body=(
            f"简历「{file.original_name or '未命名文件'}」解析失败：{reason[:200]}。"
            "请手动录入或重新上传。"
        ),
    )
    await db.commit()

async def process_file(
    db: AsyncSession, file_id: int, trace_id: str | None = None
) -> None:
    file = await db.get(ResumeFile, file_id)
    if file is None:
        return
    set_company_id(file.company_id)
    # 幂等：已解析成功过且已归属候选人的文件不重复解析
    if file.status == RF_SUCCESS and file.candidate_id:
        return

    file.status = RF_PARSING
    file.error_reason = None
    await db.commit()

    try:
        data = get_storage().get(file.object_key)
        text, parser_name, meta = await _extract_content(data, file)
        payload, confidence, extract_meta = await extract_resume(
            text,
            job_id=file.applied_job_id,
            user_id=file.uploaded_by,
            trace_id=trace_id,
        )
        meta["extract"] = extract_meta

        candidate = await _merge_candidate(db, file, payload)

        # 旧版本降级为非主简历
        await db.execute(
            update(Resume)
            .where(Resume.candidate_id == candidate.id, Resume.is_primary.is_(True))
            .values(is_primary=False)
        )
        last_version = (await db.execute(
            select(func.max(Resume.version)).where(Resume.candidate_id == candidate.id)
        )).scalar() or 0

        resume = Resume(
            company_id=file.company_id,
            candidate_id=candidate.id,
            file_id=file.id,
            structured=payload,
            field_confidence=confidence,
            plain_text=text[:200000],
            parser_meta=meta,
            content_hash=sha256_hex(text[:200000]),
            is_primary=True,
            version=last_version + 1,
        )
        db.add(resume)

        candidate.resume_text = text[:200000]
        file.candidate_id = candidate.id
        file.status = RF_SUCCESS
        file.parser = parser_name
        file.parsed_time = utcnow()
        file.error_reason = None

        await audit.write_audit(
            db, action="resume.parsed", target_type="resume_file",
            target_id=file.id, user_id=file.uploaded_by,
            detail={
                "candidate_id": candidate.id,
                "parser": parser_name,
                "source": extract_meta.get("source"),
                "low_confidence": [
                    key for key, value in confidence.items()
                    if value < settings.LOW_CONFIDENCE_THRESHOLD
                ],
            },
        )
        await notification_svc.create_notification(
            db,
            user_id=file.uploaded_by,
            candidate_id=candidate.id,
            template="resume_parsed",
            subject="简历解析完成",
            body=(
                f"简历「{file.original_name or '未命名文件'}」解析完成，"
                f"已生成候选人档案：{candidate.name}。"
            ),
        )
        await db.commit()

        # 解析成功后再写向量索引；失败只记日志，不影响建档结果
        try:
            from app.services import rag
            await rag.index_resume(db, candidate.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("简历向量索引失败 candidate_id={}：{}", candidate.id, exc)

    except ParseError as exc:
        # 乱码 / 扫描件 / 损坏文件：只落失败状态，提示手动录入，不抛 500
        file.status = RF_FAILED
        file.error_reason = str(exc)[:500]
        file.parsed_time = utcnow()
        await audit.write_audit(
            db, action="resume.parse_failed", target_type="resume_file",
            target_id=file.id, user_id=file.uploaded_by, detail={"reason": str(exc)[:500]},
        )
        await notification_svc.create_notification(
            db,
            user_id=file.uploaded_by,
            candidate_id=file.candidate_id,
            template="resume_parse_failed",
            subject="简历解析失败",
            body=(
                f"简历「{file.original_name or '未命名文件'}」解析失败：{str(exc)[:200]}。"
                "请手动录入或重新上传。"
            ),
        )
        await db.commit()

async def _extract_content(data: bytes, file: ResumeFile) -> tuple[str, str, dict]:
    ext = (file.ext or "").lower()

    if ext in IMAGE_EXTS:
        return await _vision_text(data, file.mime or "image/png", "vision", file)

    if ext == ".pdf":
        try:
            return extract_text(data, ext)
        except ParseError as pdf_error:
            # 无文字层的扫描件：渲染前 3 页走视觉模型
            images = render_pdf_images(data)
            if not images:
                raise pdf_error
            try:
                text = "\n".join([
                    await vision.image_to_text(
                        image,
                        "image/png",
                        job_id=file.applied_job_id,
                        user_id=file.uploaded_by,
                    )
                    for image in images
                ])
            except vision.VisionError as exc:
                raise ParseError("PDF 无文字层且图片识别失败，请手动录入") from exc
            return ensure_quality(text), "pdf+vision", {"engine": "pdf+vision", "pages": len(images)}

    return extract_text(data, ext)

async def _vision_text(
    data: bytes, mime: str, parser_name: str, file: ResumeFile
) -> tuple[str, str, dict]:
    try:
        text = await vision.image_to_text(
            data,
            mime,
            job_id=file.applied_job_id,
            user_id=file.uploaded_by,
        )
    except vision.VisionError as exc:
        logger.warning(f"图片识别失败：{exc}")
        raise ParseError("图片识别失败（视觉模型未配置或图片不清晰），请手动录入") from exc
    return ensure_quality(text), parser_name, {"engine": parser_name}

# ---------------------------------------------------------------- 去重合并
async def _merge_candidate(db: AsyncSession, file: ResumeFile, payload: dict) -> Candidate:
    basic = payload.get("basic") or {}
    phone = normalize_phone(basic.get("phone"))
    email = (basic.get("email") or "").strip().lower() or None
    key = _dedupe_key(phone, email, f"file:{file.sha256}")

    conditions = [Candidate.dedupe_key == key]
    if phone:
        conditions.append(Candidate.phone_hash == sha256_hex(phone))
    if email:
        conditions.append(Candidate.email_hash == sha256_hex(email))

    candidate = (await db.execute(
        select(Candidate).where(
            Candidate.company_id == file.company_id,
            Candidate.is_deleted.is_(False),
            or_(*conditions),
        )
    )).scalars().first()

    created = False
    if candidate is None:
        candidate = Candidate(company_id=file.company_id, dedupe_key=key, created_by=file.uploaded_by, skills=[])
        try:
            async with db.begin_nested():
                db.add(candidate)
                await db.flush()
            created = True
        except IntegrityError:
            candidate = (await db.execute(
                select(Candidate).where(
                    Candidate.company_id == file.company_id,
                    Candidate.dedupe_key == key,
                    Candidate.is_deleted.is_(False),
                )
            )).scalars().first()
            if candidate is None:
                raise

    # 联系方式补齐后升级为更强的判重键（邮箱 → 手机号）
    if candidate.dedupe_key != key:
        taken = (await db.execute(
            select(Candidate.id).where(
                Candidate.company_id == file.company_id,
                Candidate.dedupe_key == key,
                Candidate.id != candidate.id,
            )
        )).scalars().first()
        if taken is None:
            candidate.dedupe_key = key

    _apply_payload(candidate, payload, phone, email)
    await db.flush()

    if not created:
        await audit.write_audit(
            db, action="candidate.merge", target_type="candidate",
            target_id=candidate.id, user_id=file.uploaded_by,
            detail={"file_id": file.id, "dedupe_key": key},
        )
    return candidate

def _apply_payload(candidate: Candidate, payload: dict, phone: str | None, email: str | None) -> None:
    basic = payload.get("basic") or {}

    if phone:
        candidate.phone_enc = encrypt_pii(phone)
        candidate.phone_hash = sha256_hex(phone)
    if email:
        candidate.email_enc = encrypt_pii(email)
        candidate.email_hash = sha256_hex(email)

    if basic.get("name"):
        candidate.name = basic["name"][:100]
    if basic.get("city"):
        candidate.city = basic["city"][:100]
    if basic.get("current_company"):
        candidate.current_company = basic["current_company"][:100]
    if basic.get("current_title"):
        candidate.current_title = basic["current_title"][:100]
    if basic.get("years_experience") is not None:
        candidate.years_experience = Decimal(str(round(float(basic["years_experience"]), 1)))

    education = payload.get("education") or []
    if education:
        first = education[0]
        if first.get("school"):
            candidate.school = first["school"][:100]
        if first.get("major"):
            candidate.major = first["major"][:100]
        level = _edu_level(first.get("degree") or basic.get("highest_education"))
        if level:
            candidate.education_level = level
    elif basic.get("highest_education"):
        level = _edu_level(basic["highest_education"])
        if level:
            candidate.education_level = level

    merged = list(dict.fromkeys([*(candidate.skills or []), *(payload.get("skills") or [])]))
    candidate.skills = merged[:100]

# ---------------------------------------------------------------- 重新解析
async def reparse_file(db: AsyncSession, file_id: int, user_id: int) -> ResumeFile:
    file = await get_file_or_404(db, file_id)
    if file.status == RF_PARSING:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail="文件正在解析中，请稍后再试")

    file.status = RF_PENDING
    file.error_reason = None
    file.retry_count = (file.retry_count or 0) + 1
    await audit.write_audit(
        db, action="resume.reparse", target_type="resume_file",
        target_id=file.id, user_id=user_id,
        detail={"retry_count": file.retry_count},
    )
    await db.commit()
    return file

# ---------------------------------------------------------------- 360° 概览
async def get_candidate_overview(
    db: AsyncSession, user, candidate_id: int
) -> CandidateOverviewOut:
    """候选人 360°：档案 + 应聘记录 + 匹配结果 + 时间线（按数据范围过滤）"""
    candidate = await get_candidate_or_404(db, candidate_id)
    detail = await get_candidate_detail(db, candidate_id)

    # 应聘记录：只保留当前用户有权查看的职位
    application_rows = (await db.execute(
        select(Application, Job)
        .join(Job, Job.id == Application.job_id)
        .where(Application.candidate_id == candidate.id)
        .order_by(Application.applied_at.desc(), Application.id.desc())
    )).all()
    applications: list[tuple[Application, Job]] = [
        (application, job)
        for application, job in application_rows
        if scope.can_read_job(user, job)
    ]

    application_ids = [application.id for application, _ in applications]
    question_counts: dict[int, int] = {}
    histories: list[ApplicationStageHistory] = []
    if application_ids:
        rows = await db.execute(
            select(InterviewQuestion.application_id, func.count())
            .where(InterviewQuestion.application_id.in_(application_ids))
            .group_by(InterviewQuestion.application_id)
        )
        question_counts = {app_id: count for app_id, count in rows.all()}
        histories = list((await db.execute(
            select(ApplicationStageHistory)
            .where(ApplicationStageHistory.application_id.in_(application_ids))
            .order_by(ApplicationStageHistory.create_time.asc())
        )).scalars().all())

    job_titles = {job.id: job.title for _, job in applications}

    # 匹配结果：同样过滤掉无权查看的职位
    match_rows = (await db.execute(
        select(MatchResult, Job)
        .join(Job, Job.id == MatchResult.job_id)
        .where(MatchResult.candidate_id == candidate.id)
        .order_by(MatchResult.score.desc(), MatchResult.id.desc())
    )).all()
    matches = [
        CandidateMatchOut(
            id=match.id,
            job_id=match.job_id,
            job_title=job.title,
            score=float(match.score),
            skill_score=match.skill_score,
            exp_score=match.exp_score,
            edu_score=match.edu_score,
            matched_skills=list(match.matched_skills or []),
            missing_skills=list(match.missing_skills or []),
            summary=match.summary,
            feedback=match.feedback,
            create_time=match.create_time,
        )
        for match, job in match_rows
        if scope.can_read_job(user, job)
    ]

    timeline: list[CandidateTimelineItemOut] = [
        CandidateTimelineItemOut(
            time=candidate.create_time,
            kind="candidate",
            title="候选人建档",
        )
    ]
    for file in detail.files:
        timeline.append(CandidateTimelineItemOut(
            time=file.create_time,
            kind="resume",
            title="上传简历",
            description=file.original_name,
        ))
        if file.parsed_time is not None and file.status == RF_SUCCESS:
            timeline.append(CandidateTimelineItemOut(
                time=file.parsed_time,
                kind="parse",
                title="简历解析完成",
                description=f"{file.parser or '规则解析'} · {file.original_name}",
            ))
    for application, job in applications:
        timeline.append(CandidateTimelineItemOut(
            time=application.applied_at,
            kind="application",
            title=f"加入流程 · {job.title}",
            description=APP_STATUS_LABELS.get(application.status, application.status),
            application_id=application.id,
            job_id=job.id,
        ))
    for history in histories:
        from_label = APP_STATUS_LABELS.get(history.from_status or "", "进入流程")
        to_label = APP_STATUS_LABELS.get(history.to_status, history.to_status)
        timeline.append(CandidateTimelineItemOut(
            time=history.create_time,
            kind="stage",
            title=f"{from_label} → {to_label}",
            description=history.note,
            application_id=history.application_id,
            job_id=next(
                (
                    application.job_id
                    for application, _ in applications
                    if application.id == history.application_id
                ),
                None,
            ),
        ))
    timeline.sort(key=lambda item: item.time, reverse=True)

    return CandidateOverviewOut(
        **detail.model_dump(),
        applications=[
            CandidateApplicationOut(
                id=application.id,
                job_id=application.job_id,
                job_title=job.title,
                department=job.department,
                status=application.status,
                status_label=APP_STATUS_LABELS.get(application.status, application.status),
                source=application.source,
                match_score=float(application.match_score)
                if application.match_score is not None else None,
                applied_at=application.applied_at,
                stage_entered_at=application.stage_entered_at,
                rejected_reason=application.rejected_reason,
                hired_at=application.hired_at,
                question_count=question_counts.get(application.id, 0),
            )
            for application, job in applications
        ],
        matches=matches,
        timeline=timeline[:60],
    )