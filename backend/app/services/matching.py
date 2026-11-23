"""
人岗匹配编排：批量评分 → 缓存 → 落库 → 排名

缓存指纹 = sha256(算分版本 + jd_version + candidate.resume.content_hash)
指纹不变时直接复用已有 match_result，不重复计算、不重复调 LLM。
JD 版本、主简历内容或打分算法变化后，旧指纹结果会被清理，避免排名列表出现同一候选人多条记录。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scoring_config import SCORING_VERSION
from app.core.security import sha256_hex
from app.core.tenant import require_company_id
from app.models.candidate import Candidate, Resume
from app.models.job import Job
from app.models.match_result import MatchResult
from app.services.explain import build_explanation
from app.services.match_features import extract_features
from app.services.scorer import compute_scores
from app.services.skills import load_skill_map

@dataclass
class MatchRun:
    """一次匹配执行结果：items 已按分数降序"""

    items: list[MatchResult] = field(default_factory=list)
    cached_count: int = 0
    computed_count: int = 0

def _fingerprint(job_version: int, resume_hash: str | None) -> str:
    raw = f"{SCORING_VERSION}:v{job_version}:{resume_hash or ''}"
    return sha256_hex(raw)

async def _load_candidates(db: AsyncSession) -> list[Candidate]:
    result = await db.execute(
        select(Candidate).where(
            Candidate.is_deleted.is_(False),
            Candidate.company_id == require_company_id(),
        )
    )
    return list(result.scalars().all())

async def _load_primary_resumes(
    db: AsyncSession, candidate_ids: list[int]
) -> dict[int, Resume]:
    """一次取回主简历，避免逐人查询；同一人取版本号最高的一份"""
    if not candidate_ids:
        return {}
    rows = (
        await db.execute(
            select(Resume)
            .where(
                Resume.candidate_id.in_(candidate_ids),
                Resume.is_primary.is_(True),
            )
            .order_by(Resume.candidate_id, Resume.version.desc())
        )
    ).scalars().all()

    primary: dict[int, Resume] = {}
    for resume in rows:
        primary.setdefault(resume.candidate_id, resume)
    return primary

async def match_job(
    db: AsyncSession,
    job: Job,
    use_llm: bool = False,
    trace_id: str | None = None,
) -> MatchRun:
    """
    对一个职位匹配全库候选人。
    - 指纹命中的候选人直接复用
    - 指纹变化或无记录的重新计算并落库，同时清理该候选人的旧指纹记录
    """
    all_skill_ids = list(set([*(job.must_have_skills or []), *(job.skills or [])]))
    skill_map = await load_skill_map(db, all_skill_ids)

    candidates = await _load_candidates(db)
    candidate_ids = [cand.id for cand in candidates]
    resumes = await _load_primary_resumes(db, candidate_ids)

    fingerprints = {
        cand.id: _fingerprint(
            job.jd_version,
            resumes[cand.id].content_hash if cand.id in resumes else None,
        )
        for cand in candidates
    }

    existing_rows = (
        await db.execute(select(MatchResult).where(MatchResult.job_id == job.id))
    ).scalars().all()
    existing_by_candidate: dict[int, list[MatchResult]] = {}
    for row in existing_rows:
        existing_by_candidate.setdefault(row.candidate_id, []).append(row)

    run = MatchRun()
    stale_row_ids: list[int] = [
        row.id
        for candidate_id, rows in existing_by_candidate.items()
        if candidate_id not in fingerprints
        for row in rows
    ]

    for cand in candidates:
        current_fp = fingerprints[cand.id]
        rows = existing_by_candidate.get(cand.id, [])
        cached = next((row for row in rows if row.fingerprint == current_fp), None)
        if cached is not None:
            run.items.append(cached)
            run.cached_count += 1
            stale_row_ids.extend(
                row.id for row in rows if row.fingerprint != current_fp
            )
            continue

        stale_row_ids.extend(row.id for row in rows)

        feats = extract_features(job, cand, skill_map)
        scores = compute_scores(feats)
        explanation = await build_explanation(
            feats,
            scores,
            use_llm=use_llm,
            job_id=job.id,
            candidate_id=cand.id,
            user_id=job.created_by,
            trace_id=trace_id,
        )

        detail = {
            "scores": scores,
            "features": {
                "must_skill_names": feats.must_skill_names,
                "nice_skill_names": feats.nice_skill_names,
                "matched_must": feats.matched_must,
                "missing_must": feats.missing_must,
                "matched_nice": feats.matched_nice,
                "missing_nice": feats.missing_nice,
                "jd_min_years": feats.jd_min_years,
                "candidate_years": feats.candidate_years,
                "years_gap": feats.years_gap,
                "jd_edu_level": feats.jd_edu_level,
                "candidate_edu_level": feats.candidate_edu_level,
                "location_match": feats.location_match,
            },
            "explanation": explanation,
        }

        run.items.append(
            MatchResult(
                job_id=job.id,
                candidate_id=cand.id,
                resume_id=resumes[cand.id].id if cand.id in resumes else None,
                score=scores["score"],
                skill_score=scores["skill_score"],
                exp_score=scores["exp_score"],
                edu_score=scores["edu_score"],
                other_score=scores["other_score"],
                matched_skills=feats.matched_must + feats.matched_nice,
                missing_skills=feats.missing_must + feats.missing_nice,
                summary=explanation["summary"],
                detail=detail,
                fingerprint=current_fp,
            )
        )
        run.computed_count += 1

    # 清理旧指纹与已删除候选人的记录，保证一个职位下每个候选人只有一条当前结果
    if stale_row_ids:
        await db.execute(
            delete(MatchResult).where(MatchResult.id.in_(stale_row_ids))
        )

    for item in run.items:
        if item.id is None:
            db.add(item)

    await db.commit()

    run.items.sort(key=lambda r: (-r.score, r.candidate_id))
    return run

async def get_match_results(db: AsyncSession, job: Job) -> list[MatchResult]:
    """
    查询某职位当前有效的匹配结果（按分数降序）。

    只保留与当前 jd_version + 主简历内容指纹一致的行，
    JD 改动后尚未重新匹配的旧结果不会混进排名。
    """
    candidates = await _load_candidates(db)
    resumes = await _load_primary_resumes(db, [c.id for c in candidates])
    current = {
        cand.id: _fingerprint(
            job.jd_version,
            resumes[cand.id].content_hash if cand.id in resumes else None,
        )
        for cand in candidates
    }

    rows = (
        await db.execute(
            select(MatchResult)
            .where(MatchResult.job_id == job.id)
            .order_by(MatchResult.score.desc(), MatchResult.candidate_id)
        )
    ).scalars().all()

    results: list[MatchResult] = []
    seen: set[int] = set()
    for row in rows:
        if row.candidate_id in seen:
            continue
        if current.get(row.candidate_id) != row.fingerprint:
            continue
        seen.add(row.candidate_id)
        results.append(row)
    return results

async def get_match_detail(db: AsyncSession, match_id: int) -> MatchResult | None:
    return await db.get(MatchResult, match_id)

async def save_feedback(db: AsyncSession, match_id: int, feedback: str) -> MatchResult | None:
    mr = await db.get(MatchResult, match_id)
    if mr is None:
        return None
    mr.feedback = feedback
    await db.commit()
    await db.refresh(mr)
    return mr