"""人岗匹配接口"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, DbSession
from app.models.candidate import Candidate
from app.schemas.match import (
    MatchDetailOut,
    MatchFeedbackIn,
    MatchItemOut,
    MatchListOut,
    MatchTriggerOut,
)
from app.services import matching as matching_svc
from app.services.job import get_job_or_404

router = APIRouter(prefix="/matching", tags=["匹配"])

async def _candidate_names(
    db: AsyncSession, candidate_ids: list[int]
) -> dict[int, str | None]:
    if not candidate_ids:
        return {}
    rows = await db.execute(
        select(Candidate.id, Candidate.name).where(
            Candidate.id.in_(set(candidate_ids))
        )
    )
    return {candidate_id: name for candidate_id, name in rows.all()}

def _to_item(mr, names: dict[int, str | None]) -> MatchItemOut:
    item = MatchItemOut.model_validate(mr)
    return item.model_copy(update={"candidate_name": names.get(mr.candidate_id)})

@router.post("/jobs/{job_id}/match", response_model=MatchTriggerOut)
async def trigger_match(
    job_id: int,
    db: DbSession,
    user: CurrentUser,
    use_llm: bool = Query(default=False, description="是否用 LLM 润色理由"),
):
    """对职位执行匹配（规则分同步计算；LLM 理由可选）"""
    job = await get_job_or_404(db, job_id)
    run = await matching_svc.match_job(db, job, use_llm=use_llm)

    names = await _candidate_names(db, [mr.candidate_id for mr in run.items])
    items = [_to_item(mr, names) for mr in run.items]
    return MatchTriggerOut(
        job_id=job.id,
        matched_count=len(items),
        cached_count=run.cached_count,
        computed_count=run.computed_count,
        items=items,
    )

@router.get("/jobs/{job_id}/matches", response_model=MatchListOut)
async def list_matches(
    job_id: int,
    db: DbSession,
    user: CurrentUser,
    min_score: float = Query(default=0.0, ge=0, le=100),
    sort: str = Query(default="score", pattern="^(score|skill_score|exp_score)$"),
):
    """查询某职位的匹配排名"""
    job = await get_job_or_404(db, job_id)
    results = await matching_svc.get_match_results(db, job)

    if min_score > 0:
        results = [r for r in results if r.score >= min_score]

    # 默认已按 score 降序；如需按子项排序
    if sort != "score":
        results.sort(key=lambda r: getattr(r, sort, 0) or 0, reverse=True)

    names = await _candidate_names(db, [r.candidate_id for r in results])
    items = [_to_item(r, names) for r in results]
    return MatchListOut(items=items, total=len(items), job_id=job.id, job_title=job.title)

@router.get("/matches/{match_id}", response_model=MatchDetailOut)
async def get_match(match_id: int, db: DbSession, user: CurrentUser):
    """单条匹配详情（含命中/缺失/理由明细）"""
    mr = await matching_svc.get_match_detail(db, match_id)
    if mr is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="匹配结果不存在")
    names = await _candidate_names(db, [mr.candidate_id])
    detail = MatchDetailOut.model_validate(mr)
    return detail.model_copy(update={"candidate_name": names.get(mr.candidate_id)})

@router.post("/matches/{match_id}/feedback", response_model=MatchDetailOut)
async def feedback(
    match_id: int,
    payload: MatchFeedbackIn,
    db: DbSession,
    user: CurrentUser,
):
    """HR 标注「合适/不合适」，用于后续校准"""
    if payload.feedback not in ("fit", "unfit"):
        raise HTTPException(status_code=400, detail="feedback 只能是 fit 或 unfit")
    mr = await matching_svc.save_feedback(db, match_id, payload.feedback)
    if mr is None:
        raise HTTPException(status_code=404, detail="匹配结果不存在")
    names = await _candidate_names(db, [mr.candidate_id])
    detail = MatchDetailOut.model_validate(mr)
    return detail.model_copy(update={"candidate_name": names.get(mr.candidate_id)})