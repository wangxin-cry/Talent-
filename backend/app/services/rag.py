"""
RAG 知识增强服务（阶段八）

职责：
1. 把简历 / 职位 / 面试题切成文本片段（rag_chunk 落库）
2. 调 embedding 后写入 FAISS（未安装时降级 numpy）
3. 提供相似简历检索（人才库）与面试题生成的参考材料
4. 所有异常内部吞掉并记录，RAG 不可用不影响主业务
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass

from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.candidate import Candidate, Resume
from app.models.application import Application
from app.models.interview_question import InterviewQuestion
from app.models.job import Job, STATUS_ARCHIVED
from app.models.rag_chunk import DOC_JOB, DOC_QUESTION, DOC_RESUME, RagChunk
from app.models.skill import Skill
from app.core.tenant import get_company_id, require_company_id, set_company_id
from app.services import embeddings, vector_store

# 同一进程内按「文档类型 + 来源」串行化索引：
# 同时上传多份简历可能归并到同一个候选人，两个后台任务并发写切片会撞唯一键
_INDEX_LOCKS: dict[str, asyncio.Lock] = {}


def _scope_lock(doc_type: str, source_id: int) -> asyncio.Lock:
    key = f"{doc_type}:{source_id}"
    lock = _INDEX_LOCKS.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _INDEX_LOCKS[key] = lock
    return lock

_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class RAGUnavailable(RuntimeError):
    """RAG 不可用（未开启 / 未配置 / 索引失败）"""


@dataclass
class Chunk:
    key: str
    content: str
    meta: dict


def _clean(text: str | None, limit: int = 1500) -> str:
    value = " ".join((text or "").split())
    value = _PHONE_RE.sub("[手机号]", value)
    value = _EMAIL_RE.sub("[邮箱]", value)
    return value[:limit]


def _enabled_for_index() -> bool:
    return (
        settings.RAG_ENABLED
        and settings.RAG_INDEX_ENABLED
        and embeddings.is_configured()
    )


def _enabled_for_search() -> bool:
    return settings.RAG_ENABLED and embeddings.is_configured()


# ---------------------------------------------------------------- 切片

def _chunk_resume(candidate: Candidate, resume: Resume | None) -> list[Chunk]:
    structured = (resume.structured if resume else None) or {}
    basic = structured.get("basic") or {}

    header = "；".join(
        part
        for part in [
            f"姓名：{candidate.name}" if candidate.name else "",
            f"当前职位：{candidate.current_title}" if candidate.current_title else "",
            f"当前公司：{candidate.current_company}" if candidate.current_company else "",
            f"工作年限：{candidate.years_experience} 年" if candidate.years_experience else "",
            f"城市：{candidate.city}" if candidate.city else "",
            f"学历：{candidate.education_level}" if candidate.education_level else "",
            f"院校：{candidate.school}" if candidate.school else "",
            f"求职意向：{basic.get('job_intention')}" if basic.get("job_intention") else "",
        ]
        if part
    )
    skills = [str(item) for item in (candidate.skills or []) if item]
    summary = candidate.resume_text or ""

    project_items = [item for item in (structured.get("projects") or [])[:4] if isinstance(item, dict)]
    work_items = [item for item in (structured.get("work") or [])[:4] if isinstance(item, dict)]
    has_detail = bool(project_items or work_items)

    # profile 片段是否附带简历全文摘要，取决于有没有更细的项目/经历片段：
    # 有明细时只保留基本信息，避免一个又长又泛的 profile 在所有查询上拿高分，
    # 把具体的项目片段压在后面（"万金油切片"问题）。
    if has_detail:
        profile = _clean(header, 800)
    else:
        profile = _clean(
            "；".join(
                part
                for part in [header, f"技能：{'、'.join(skills[:30])}" if skills else "", summary[:600]]
                if part
            )
        )

    chunks: list[Chunk] = []
    if len(profile) >= 20:
        chunks.append(
            Chunk(
                key=f"resume-{candidate.id}-profile",
                content=profile,
                meta={"chunk_type": "profile", "candidate_id": candidate.id},
            )
        )

    for index, item in enumerate(project_items):
        name = str(item.get("name") or item.get("project_name") or "").strip()
        tech = item.get("stack") or item.get("tech") or []
        if isinstance(tech, str):
            tech = [tech]
        body = _clean(
            "；".join(
                part
                for part in [
                    f"项目：{name}" if name else "",
                    f"角色：{item.get('role')}" if item.get("role") else "",
                    f"技术栈：{'、'.join(str(t) for t in tech[:8])}" if tech else "",
                    f"描述：{item.get('description') or item.get('detail') or ''}",
                ]
                if part
            )
        )
        if len(body) >= 20:
            chunks.append(
                Chunk(
                    key=f"resume-{candidate.id}-project-{index}",
                    content=body,
                    meta={"chunk_type": "project", "candidate_id": candidate.id, "name": name},
                )
            )

    for index, item in enumerate(work_items):
        company = str(item.get("company") or "").strip()
        title = str(item.get("title") or item.get("position") or "").strip()
        body = _clean(
            "；".join(
                part
                for part in [
                    f"公司：{company}" if company else "",
                    f"职位：{title}" if title else "",
                    f"描述：{item.get('description') or ''}",
                ]
                if part
            )
        )
        if len(body) >= 20:
            chunks.append(
                Chunk(
                    key=f"resume-{candidate.id}-work-{index}",
                    content=body,
                    meta={"chunk_type": "work", "candidate_id": candidate.id, "company": company},
                )
            )

    if skills:
        skill_text = _clean(f"{candidate.name or '候选人'} 的技能：{'、'.join(skills[:40])}", 500)
        chunks.append(
            Chunk(
                key=f"resume-{candidate.id}-skills",
                content=skill_text,
                meta={"chunk_type": "skills", "candidate_id": candidate.id},
            )
        )

    return chunks[:10]


def _chunk_job(job: Job, skill_names: list[str], must_names: list[str]) -> list[Chunk]:
    body = _clean(
        "；".join(
            part
            for part in [
                f"职位：{job.title}",
                f"部门：{job.department}" if job.department else "",
                f"地点：{job.location}" if job.location else "",
                f"经验要求：{job.min_years} 年" if job.min_years is not None else "",
                f"学历要求：{job.education_level}" if job.education_level else "",
                f"职责：{job.description or ''}",
                f"要求：{job.requirements or ''}",
                f"必备技能：{'、'.join(must_names[:20])}" if must_names else "",
                f"技能要求：{'、'.join(skill_names[:30])}" if skill_names else "",
            ]
            if part
        ),
        1800,
    )
    if len(body) < 20:
        return []
    return [
        Chunk(
            key=f"job-{job.id}-profile",
            content=body,
            meta={"chunk_type": "job", "job_id": job.id},
        )
    ]


def _chunk_questions(application_id: int, rows: list[InterviewQuestion]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for index, row in enumerate(rows):
        body = _clean(
            "；".join(
                part
                for part in [
                    f"面试题：{row.question}",
                    f"考察点：{row.looking_for}" if row.looking_for else "",
                    f"引用依据：{row.reference}" if row.reference else "",
                    f"追问：{row.follow_up}" if row.follow_up else "",
                ]
                if part
            ),
            800,
        )
        if len(body) < 15:
            continue
        chunks.append(
            Chunk(
                key=f"question-{application_id}-{index}",
                content=body,
                meta={
                    "chunk_type": "question",
                    "application_id": application_id,
                    "question_id": row.id,
                    "job_id": row.job_id,
                    "candidate_id": row.candidate_id,
                    "category": row.category,
                },
            )
        )
    return chunks


# ---------------------------------------------------------------- 索引

async def _load_skill_names(db: AsyncSession, ids: list[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = (
        await db.execute(select(Skill).where(Skill.id.in_(list(set(ids)))))
    ).scalars().all()
    return {row.id: (row.display_name or row.name) for row in rows}


async def _sync_scope(
    db: AsyncSession,
    doc_type: str,
    source_id: int,
    chunks: list[Chunk],
) -> int:
    # 注意：这里要连"逻辑删除"的行一起查。chunk_key 是全局唯一键，
    # 只查 is_deleted=False 会让已软删的行挡住重新插入，触发唯一键冲突。
    existing_rows = (
        await db.execute(
            select(RagChunk).where(
                RagChunk.doc_type == doc_type,
                RagChunk.source_id == source_id,
            )
        )
    ).scalars().all()
    existing = {row.chunk_key: row for row in existing_rows}
    wanted_keys = {chunk.key for chunk in chunks}

    # 向量库丢失的检测：切换后端（.npz ↔ .faiss）、删索引目录、索引损坏时，
    # 元数据还在但向量为空。此时若按"内容未变就跳过"，向量永远补不回来，
    # 语义搜索会静默返回空结果。因此一旦发现该类型向量数为 0 而元数据存在，
    # 就强制重新向量化全部切片。
    store_count = vector_store.count(doc_type)
    force_rebuild = store_count == 0 and bool(existing)

    pending: list[tuple[Chunk, RagChunk | None]] = []
    for chunk in chunks:
        row = existing.get(chunk.key)
        if not force_rebuild and row is not None and row.content == chunk.content:
            continue
        pending.append((chunk, row))

    vectors: list[list[float]] = []
    if pending:
        try:
            vectors = await embeddings.embed_texts(
                [chunk.content for chunk, _ in pending],
                feature=f"rag_index_{doc_type}",
            )
        except embeddings.EmbeddingError as exc:
            logger.warning("RAG 索引向量化失败 doc_type={}：{}", doc_type, exc)
            raise RAGUnavailable(str(exc)) from exc

    upsert_ids: list[int] = []
    upsert_vectors: list[list[float]] = []
    for (chunk, row), vector in zip(pending, vectors, strict=False):
        if row is None:
            row = RagChunk(
                doc_type=doc_type,
                source_id=source_id,
                chunk_key=chunk.key,
                content=chunk.content,
                chunk_meta=chunk.meta,
                company_id=require_company_id(),
            )
            db.add(row)
        else:
            row.content = chunk.content
            row.chunk_meta = chunk.meta
            row.is_deleted = False
        await db.flush()
        upsert_ids.append(row.id)
        upsert_vectors.append(vector)

    stale_ids = [row.id for key, row in existing.items() if key not in wanted_keys]
    if upsert_ids:
        await vector_store.upsert(doc_type, upsert_ids, upsert_vectors)
    if stale_ids:
        await vector_store.remove(doc_type, stale_ids)
        await db.execute(delete(RagChunk).where(RagChunk.id.in_(stale_ids)))

    await db.commit()
    return len(chunks)


async def index_resume(db: AsyncSession, candidate_id: int) -> int:
    if not _enabled_for_index():
        return 0
    async with _scope_lock(DOC_RESUME, candidate_id):
        try:
            candidate = await db.get(Candidate, candidate_id)
            if candidate is None or candidate.is_deleted:
                return 0
            set_company_id(candidate.company_id)
            resume = (
                await db.execute(
                    select(Resume)
                    .where(Resume.candidate_id == candidate_id, Resume.is_primary.is_(True))
                    .order_by(Resume.version.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            chunks = _chunk_resume(candidate, resume)
            return await _sync_scope(db, DOC_RESUME, candidate_id, chunks)
        except RAGUnavailable:
            return 0
        except Exception as exc:  # 索引失败不能污染调用方的 session
            await db.rollback()
            logger.warning("简历索引失败 candidate_id={}：{}", candidate_id, exc)
            return 0


async def index_job(db: AsyncSession, job_id: int) -> int:
    if not _enabled_for_index():
        return 0
    async with _scope_lock(DOC_JOB, job_id):
        try:
            job = await db.get(Job, job_id)
            if job is None:
                return 0
            set_company_id(job.company_id)
            skill_map = await _load_skill_names(
                db, list(set([*(job.must_have_skills or []), *(job.skills or [])]))
            )
            must_names = [skill_map[i] for i in (job.must_have_skills or []) if i in skill_map]
            skill_names = [skill_map[i] for i in (job.skills or []) if i in skill_map]
            chunks = _chunk_job(job, skill_names, must_names)
            return await _sync_scope(db, DOC_JOB, job.id, chunks)
        except RAGUnavailable:
            return 0
        except Exception as exc:
            await db.rollback()
            logger.warning("职位索引失败 job_id={}：{}", job_id, exc)
            return 0


async def index_questions(db: AsyncSession, application_id: int) -> int:
    if not _enabled_for_index():
        return 0
    async with _scope_lock(DOC_QUESTION, application_id):
        try:
            application = await db.get(Application, application_id)
            if application is None:
                return 0
            set_company_id(application.company_id)
            rows = (
                await db.execute(
                    select(InterviewQuestion)
                    .where(InterviewQuestion.application_id == application_id)
                    .order_by(InterviewQuestion.sort_order.asc(), InterviewQuestion.id.asc())
                )
            ).scalars().all()
            chunks = _chunk_questions(application_id, list(rows))
            return await _sync_scope(db, DOC_QUESTION, application_id, chunks)
        except RAGUnavailable:
            return 0
        except Exception as exc:
            await db.rollback()
            logger.warning("面试题索引失败 application_id={}：{}", application_id, exc)
            return 0


async def index_resume_task(candidate_id: int) -> None:
    try:
        async with SessionLocal() as db:
            await index_resume(db, candidate_id)
    except Exception as exc:  # 后台任务不能抛出
        logger.warning("后台索引简历失败 candidate_id={}：{}", candidate_id, exc)


async def index_job_task(job_id: int) -> None:
    try:
        async with SessionLocal() as db:
            await index_job(db, job_id)
    except Exception as exc:
        logger.warning("后台索引职位失败 job_id={}：{}", job_id, exc)


async def index_questions_task(application_id: int) -> None:
    try:
        async with SessionLocal() as db:
            await index_questions(db, application_id)
    except Exception as exc:
        logger.warning("后台索引面试题失败 application_id={}：{}", application_id, exc)


# ---------------------------------------------------------------- 检索

@dataclass
class ResumeHit:
    candidate_id: int
    name: str
    current_title: str
    current_company: str
    years_experience: float | None
    city: str | None
    skills: list[str]
    score: float
    snippets: list[str]


async def search_resumes(
    db: AsyncSession,
    query: str,
    *,
    top_k: int = 10,
    job_id: int | None = None,
    exclude_candidate_id: int | None = None,
    min_score: float | None = None,
    user_id: int | None = None,
    vector: list[float] | None = None,
) -> list[ResumeHit]:
    if not _enabled_for_search() or not query.strip():
        return []
    if vector is None:
        try:
            vector = await embeddings.embed_query(
                query, feature="rag_search", user_id=user_id
            )
        except embeddings.EmbeddingError as exc:
            logger.warning("RAG 检索向量化失败：{}", exc)
            return []

    allowed_candidates: set[int] | None = None
    if job_id is not None:
        allowed_candidates = set(
            (
                await db.execute(
                    select(Application.candidate_id).where(Application.job_id == job_id)
                )
            ).scalars().all()
        )
        if not allowed_candidates:
            return []

    threshold = settings.RAG_MIN_SCORE if min_score is None else min_score
    try:
        hits = await vector_store.search(DOC_RESUME, vector, max(1, top_k) * 4)
    except Exception as exc:  # noqa: BLE001
        # 向量库异常（索引损坏 / 维度不匹配 / faiss 崩溃）不能让搜索接口 500
        logger.warning("向量检索失败，返回空结果：{}", exc)
        return []
    if not hits:
        return []

    score_map = {chunk_id: score for chunk_id, score in hits}
    rows = (
        await db.execute(
            select(RagChunk).where(
                RagChunk.id.in_(list(score_map.keys())),
                RagChunk.doc_type == DOC_RESUME,
                RagChunk.is_deleted.is_(False),
            )
        )
    ).scalars().all()

    grouped: dict[int, dict] = {}
    chunk_rows: dict[int, list[RagChunk]] = {}
    company_id = get_company_id()
    if company_id is None:
        return []
    for row in rows:
        if row.company_id != company_id:
            continue
        candidate_id = row.source_id
        if exclude_candidate_id is not None and candidate_id == exclude_candidate_id:
            continue
        if allowed_candidates is not None and candidate_id not in allowed_candidates:
            continue
        score = score_map.get(row.id, 0.0)
        if score < threshold:
            continue
        bucket = grouped.setdefault(
            candidate_id,
            {"score": score, "snippets": []},
        )
        bucket["score"] = max(bucket["score"], score)
        chunk_rows.setdefault(candidate_id, []).append(row)

    # 片段展示优先级：项目/经历 > 技能 > 基本信息
    # 基础信息片段较长较泛，仅在没有项目/经历命中时作为兜底展示。
    _ORDER = {"project": 0, "work": 1, "skills": 2, "profile": 3}
    for candidate_id, bucket in grouped.items():
        ordered = sorted(
            chunk_rows.get(candidate_id, []),
            key=lambda r: _ORDER.get((r.chunk_meta or {}).get("chunk_type", "profile"), 9),
        )
        for row in ordered[:2]:
            if row.content not in bucket["snippets"]:
                bucket["snippets"].append(row.content[:220])

    if not grouped:
        return []

    candidates = (
        await db.execute(select(Candidate).where(Candidate.id.in_(list(grouped.keys()))))
    ).scalars().all()
    candidate_map = {item.id: item for item in candidates}

    result: list[ResumeHit] = []
    for candidate_id, bucket in grouped.items():
        candidate = candidate_map.get(candidate_id)
        if candidate is None or candidate.is_deleted:
            continue
        result.append(
            ResumeHit(
                candidate_id=candidate.id,
                name=candidate.name or f"候选人 {candidate.id}",
                current_title=candidate.current_title or "",
                current_company=candidate.current_company or "",
                years_experience=(
                    float(candidate.years_experience)
                    if candidate.years_experience is not None
                    else None
                ),
                city=candidate.city,
                skills=list(candidate.skills or [])[:10],
                score=round(bucket["score"], 4),
                snippets=bucket["snippets"],
            )
        )

    result.sort(key=lambda item: item.score, reverse=True)
    return result[: max(1, top_k)]


async def retrieve_for_interview(
    db: AsyncSession,
    application,
    job: Job | None,
    candidate: Candidate | None,
) -> list[dict]:
    """面试题生成的参考材料；任何异常都返回空列表"""
    if not _enabled_for_search() or job is None:
        return []

    skill_map = await _load_skill_names(
        db, list(set([*(job.must_have_skills or []), *(job.skills or [])]))
    )
    must_names = [skill_map[i] for i in (job.must_have_skills or []) if i in skill_map]
    query = _clean(
        "；".join(
            part
            for part in [
                f"职位：{job.title}",
                f"必备技能：{'、'.join(must_names)}" if must_names else "",
                f"要求：{job.requirements or ''}"[:400],
                f"候选人：{candidate.current_title}" if candidate and candidate.current_title else "",
            ]
            if part
        ),
        600,
    )
    if not query:
        return []

    try:
        vector = await embeddings.embed_query(
            query,
            feature="rag_interview_context",
            job_id=job.id,
            candidate_id=application.candidate_id,
            user_id=application.created_by,
        )
        resume_hits = await search_resumes(
            db,
            query,
            top_k=settings.RAG_SIMILAR_RESUMES,
            exclude_candidate_id=application.candidate_id,
            user_id=application.created_by,
            vector=vector,
        )

        raw_question_hits = await vector_store.search(
            DOC_QUESTION, vector, max(1, settings.RAG_SIMILAR_QUESTIONS) * 3
        )
        q_score = {chunk_id: score for chunk_id, score in raw_question_hits}
        q_rows = (
            await db.execute(
                select(RagChunk).where(
                    RagChunk.id.in_(list(q_score.keys())),
                    RagChunk.doc_type == DOC_QUESTION,
                    RagChunk.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        # 同职位优先，其次按相似度
        q_rows.sort(
            key=lambda row: (
                (row.chunk_meta or {}).get("job_id") != job.id,
                -q_score.get(row.id, 0.0),
            )
        )

        sources: list[dict] = []
        for hit in resume_hits[: settings.RAG_SIMILAR_RESUMES]:
            sources.append(
                {
                    "type": "resume",
                    "id": hit.candidate_id,
                    "title": f"相似候选人：{hit.name}（{hit.current_title or '未知职位'}）",
                    "score": hit.score,
                    "snippet": hit.snippets[0] if hit.snippets else "",
                }
            )
        for row in q_rows[: settings.RAG_SIMILAR_QUESTIONS]:
            sources.append(
                {
                    "type": "question",
                    "id": (row.chunk_meta or {}).get("question_id") or row.id,
                    "title": f"历史面试题（{(row.chunk_meta or {}).get('category') or '综合'}）",
                    "score": round(q_score.get(row.id, 0.0), 4),
                    "snippet": row.content[:240],
                }
            )
        return sources
    except Exception as exc:
        logger.warning("RAG 面试参考材料检索失败：{}", exc)
        return []


# ---------------------------------------------------------------- 健康与重建

def health() -> dict:
    def _count(doc_type: str) -> int:
        try:
            return vector_store.count(doc_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取向量集合数量失败 {}：{}", doc_type, exc)
            return 0

    collections = {
        DOC_RESUME: _count(DOC_RESUME),
        DOC_JOB: _count(DOC_JOB),
        DOC_QUESTION: _count(DOC_QUESTION),
    }
    return {
        "enabled": settings.RAG_ENABLED,
        "index_enabled": settings.RAG_INDEX_ENABLED,
        "backend": vector_store.backend_name(),
        "embedding_configured": embeddings.is_configured(),
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": settings.MODEL_EMBEDDING,
        "dim": settings.EMBEDDING_DIM,
        "collections": collections,
    }


async def consistency(db: AsyncSession) -> dict:
    """
    向量库与元数据的一致性检查

    切换 VECTOR_BACKEND、手删索引目录、索引损坏后，rag_chunk 仍在但向量为空。
    该函数用于暴露这种状态，配合 /rag/reindex?rebuild=true 修复。
    """
    expected = {
        DOC_RESUME: (
            await db.execute(
                select(func.count()).select_from(RagChunk).where(
                    RagChunk.doc_type == DOC_RESUME, RagChunk.is_deleted.is_(False)
                )
            )
        ).scalar_one(),
        DOC_JOB: (
            await db.execute(
                select(func.count()).select_from(RagChunk).where(
                    RagChunk.doc_type == DOC_JOB, RagChunk.is_deleted.is_(False)
                )
            )
        ).scalar_one(),
        DOC_QUESTION: (
            await db.execute(
                select(func.count()).select_from(RagChunk).where(
                    RagChunk.doc_type == DOC_QUESTION, RagChunk.is_deleted.is_(False)
                )
            )
        ).scalar_one(),
    }

    actual: dict[str, int] = {}
    for doc_type in (DOC_RESUME, DOC_JOB, DOC_QUESTION):
        try:
            actual[doc_type] = vector_store.count(doc_type)
        except Exception:  # noqa: BLE001
            actual[doc_type] = 0

    mismatched = [k for k in expected if expected[k] != actual[k]]
    return {
        "consistent": not mismatched,
        "expected": {k: int(v) for k, v in expected.items()},
        "actual": actual,
        "mismatched": mismatched,
    }


async def reindex_all(db: AsyncSession, scope: str = "all", rebuild: bool = False) -> dict:
    """
    全量重建：rebuild=True 时先清空向量与切片

    若调用方没有显式要求 rebuild，但检测到向量库与元数据不一致
    （切换 VECTOR_BACKEND、索引文件被删、索引损坏），会自动升级为 rebuilt=True。
    否则 _sync_scope 会认为"内容未变"而跳过，向量永远补不回来。
    """
    if not rebuild:
        try:
            check = await consistency(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("一致性检查失败，按增量索引处理：{}", exc)
            check = {"consistent": True, "mismatched": []}
        if not check.get("consistent", True):
            logger.warning(
                "向量库与元数据不一致（{}），自动改为全量重建", check.get("mismatched")
            )
            rebuild = True

    company_id = require_company_id()

    if rebuild:
        # 租户隔离：只清当前公司的切片与向量，不能 reset 全局索引
        scope_to_doc = {
            "resumes": DOC_RESUME,
            "jobs": DOC_JOB,
            "questions": DOC_QUESTION,
        }
        if scope == "all":
            targets = [DOC_RESUME, DOC_JOB, DOC_QUESTION]
        else:
            mapped = scope_to_doc.get(scope)
            targets = [mapped] if mapped else []
        for doc_type in targets:
            stale_ids = (
                await db.execute(
                    select(RagChunk.id).where(
                        RagChunk.doc_type == doc_type, RagChunk.company_id == company_id
                    )
                )
            ).scalars().all()
            if stale_ids:
                await vector_store.remove(doc_type, list(stale_ids))
            await db.execute(
                delete(RagChunk).where(
                    RagChunk.doc_type == doc_type, RagChunk.company_id == company_id
                )
            )
        await db.commit()

    counts = {"resume": 0, "job": 0, "question": 0}

    if scope in ("all", "resumes"):
        candidate_ids = (
            await db.execute(
                select(Candidate.id).where(
                    Candidate.is_deleted.is_(False), Candidate.company_id == company_id
                )
            )
        ).scalars().all()
        for candidate_id in candidate_ids:
            counts["resume"] += await index_resume(db, candidate_id)

    if scope in ("all", "jobs"):
        job_ids = (
            await db.execute(
                select(Job.id).where(
                    Job.status != STATUS_ARCHIVED, Job.company_id == company_id
                )
            )
        ).scalars().all()
        for job_id in job_ids:
            counts["job"] += await index_job(db, job_id)

    if scope in ("all", "questions"):
        application_ids = (
            await db.execute(
                select(InterviewQuestion.application_id)
                .where(InterviewQuestion.company_id == company_id)
                .distinct()
            )
        ).scalars().all()
        for application_id in application_ids:
            counts["question"] += await index_questions(db, application_id)

    return counts
