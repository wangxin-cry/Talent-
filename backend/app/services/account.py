"""账号注销：招聘专员 / 用人经理自助注销，并清理其创建的业务数据"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

from app.core.security import verify_password
from app.core.storage import get_storage
from app.core.tenant import require_company_id
from app.models.api_key import ApiKey
from app.models.application import Application, ApplicationStageHistory
from app.models.auth_token import AuthToken
from app.models.candidate import Candidate, Resume, ResumeFile
from app.models.chat import ChatMessage, ChatSession
from app.models.interview import (
    ApplicationTracking,
    InterviewFeedback,
    InterviewSchedule,
)
from app.models.interview_question import InterviewQuestion
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.notification import Notification
from app.models.rag_chunk import DOC_JOB, DOC_QUESTION, DOC_RESUME, RagChunk
from app.models.user import ROLE_MANAGER, ROLE_RECRUITER, STATUS_DELETED, User
from app.services import vector_store

CANCELLABLE_ROLES = (ROLE_RECRUITER, ROLE_MANAGER)


async def cancel_account(db: AsyncSession, user: User, password: str) -> dict:
    """注销当前账号：校验身份 → 清理其创建的数据 → 软删除账号"""
    if user.role not in CANCELLABLE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅招聘专员和用人经理可自助注销账号，请联系公司管理员",
        )
    if not verify_password(password, user.password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="密码不正确")

    company_id = require_company_id()

    job_ids = list(
        (
            await db.execute(
                select(Job.id).where(
                    Job.company_id == company_id, Job.created_by == user.id
                )
            )
        ).scalars()
    )
    candidate_ids = list(
        (
            await db.execute(
                select(Candidate.id).where(
                    Candidate.company_id == company_id, Candidate.created_by == user.id
                )
            )
        ).scalars()
    )

    app_conditions = []
    if job_ids:
        app_conditions.append(Application.job_id.in_(job_ids))
    if candidate_ids:
        app_conditions.append(Application.candidate_id.in_(candidate_ids))
    app_ids = (
        list(
            (
                await db.execute(
                    select(Application.id).where(
                        Application.company_id == company_id, or_(*app_conditions)
                    )
                )
            ).scalars()
        )
        if app_conditions
        else []
    )

    # 待清理的 RAG 切片（简历 / 职位 / 面试题），以及需要从向量库移除的 id
    chunk_conditions = []
    if candidate_ids:
        chunk_conditions.append(
            (RagChunk.doc_type == DOC_RESUME) & RagChunk.source_id.in_(candidate_ids)
        )
    if job_ids:
        chunk_conditions.append(
            (RagChunk.doc_type == DOC_JOB) & RagChunk.source_id.in_(job_ids)
        )
    if app_ids:
        chunk_conditions.append(
            (RagChunk.doc_type == DOC_QUESTION) & RagChunk.source_id.in_(app_ids)
        )
    vector_targets: dict[str, list[int]] = {}
    if chunk_conditions:
        chunks = (
            await db.execute(
                select(RagChunk.id, RagChunk.doc_type).where(
                    RagChunk.company_id == company_id, or_(*chunk_conditions)
                )
            )
        ).all()
        for chunk_id, doc_type in chunks:
            vector_targets.setdefault(doc_type, []).append(chunk_id)
        await db.execute(
            delete(RagChunk).where(
                RagChunk.company_id == company_id, or_(*chunk_conditions)
            )
        )

    # 收集简历文件，稍后删除对象存储里的本体
    files: list[ResumeFile] = []
    if candidate_ids:
        files = list(
            (
                await db.execute(
                    select(ResumeFile).where(
                        ResumeFile.company_id == company_id,
                        ResumeFile.candidate_id.in_(candidate_ids),
                    )
                )
            ).scalars()
        )

    session_ids = list(
        (
            await db.execute(
                select(ChatSession.id).where(
                    ChatSession.company_id == company_id, ChatSession.user_id == user.id
                )
            )
        ).scalars()
    )
    if session_ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids)))
        await db.execute(delete(ChatSession).where(ChatSession.id.in_(session_ids)))

    await db.execute(
        delete(Notification).where(
            Notification.company_id == company_id,
            or_(
                Notification.user_id == user.id,
                Notification.application_id.in_(app_ids) if app_ids else Notification.id == 0,
            ),
        )
    )
    await db.execute(
        delete(ApiKey).where(ApiKey.company_id == company_id, ApiKey.user_id == user.id)
    )
    await db.execute(delete(AuthToken).where(AuthToken.user_id == user.id))

    if app_ids:
        await db.execute(
            delete(ApplicationTracking).where(
                ApplicationTracking.application_id.in_(app_ids)
            )
        )
        await db.execute(
            delete(InterviewFeedback).where(InterviewFeedback.application_id.in_(app_ids))
        )
        await db.execute(
            delete(InterviewSchedule).where(InterviewSchedule.application_id.in_(app_ids))
        )
        await db.execute(
            delete(InterviewQuestion).where(InterviewQuestion.application_id.in_(app_ids))
        )
        await db.execute(
            delete(ApplicationStageHistory).where(
                ApplicationStageHistory.application_id.in_(app_ids)
            )
        )
        await db.execute(delete(Application).where(Application.id.in_(app_ids)))

    if job_ids or candidate_ids:
        match_conditions = []
        if job_ids:
            match_conditions.append(MatchResult.job_id.in_(job_ids))
        if candidate_ids:
            match_conditions.append(MatchResult.candidate_id.in_(candidate_ids))
        await db.execute(delete(MatchResult).where(or_(*match_conditions)))

    if candidate_ids:
        await db.execute(delete(Resume).where(Resume.candidate_id.in_(candidate_ids)))
        await db.execute(
            delete(ResumeFile).where(ResumeFile.candidate_id.in_(candidate_ids))
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
    if job_ids:
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))

    # 软删除账号并释放登录名 / 邮箱，保留审计可追溯性
    avatar_key = user.avatar_key
    user.status = STATUS_DELETED
    user.token_version += 1
    user.name = f"deleted_{user.id}"
    user.email = f"deleted_{user.id}@talentmatch.invalid"
    user.phone = None
    user.avatar_key = None
    user.department = None
    await db.commit()

    # 对象存储与向量索引属于外部副作用，失败只告警，不影响注销结果
    if avatar_key:
        try:
            get_storage().delete(avatar_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"注销账号时删除头像失败 | key={avatar_key} | {exc}")
    for file in files:
        try:
            get_storage().delete(file.object_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"注销账号时删除简历文件失败 | key={file.object_key} | {exc}")
    for doc_type, ids in vector_targets.items():
        try:
            await vector_store.remove(doc_type, ids)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"注销账号时清理向量索引失败 | {doc_type} | {exc}")

    return {
        "deleted_jobs": len(job_ids),
        "deleted_candidates": len(candidate_ids),
        "deleted_applications": len(app_ids),
        "deleted_files": len(files),
    }
