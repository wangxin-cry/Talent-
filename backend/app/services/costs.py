"""
AI 成本计量服务（阶段七）

- record_ai_call：每次真实 LLM 调用写一条台账，使用独立会话提交，
  不污染业务事务，也不会因为业务回滚而丢账。
- 成本分页 / 汇总 / 预算告警
"""
from __future__ import annotations

from datetime import datetime

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.pricing import estimate_cost
from app.models.ai_call import AI_STATUS_SUCCESS, AiCall
from app.models.base import utcnow
from app.models.job import Job


async def record_ai_call(
    *,
    feature: str,
    model: str | None,
    provider: str | None = "siliconflow",
    input_tokens: int = 0,
    output_tokens: int = 0,
    duration_ms: int | None = None,
    status: str = AI_STATUS_SUCCESS,
    error_reason: str | None = None,
    user_id: int | None = None,
    job_id: int | None = None,
    candidate_id: int | None = None,
    agent: str | None = None,
    cache_hit: bool = False,
    trace_id: str | None = None,
) -> None:
    """写入一条调用台账；记账失败只告警，不影响业务"""
    input_tokens = max(0, int(input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    cost = 0.0 if cache_hit else estimate_cost(model, input_tokens, output_tokens)

    try:
        async with SessionLocal() as session:
            session.add(
                AiCall(
                    feature=feature,
                    agent=agent,
                    provider=provider,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=input_tokens + output_tokens,
                    cost=cost,
                    duration_ms=duration_ms,
                    cache_hit=cache_hit,
                    status=status,
                    error_reason=(error_reason or "")[:500] or None,
                    user_id=user_id,
                    job_id=job_id,
                    candidate_id=candidate_id,
                    trace_id=trace_id,
                    company_id=1,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"AI 调用记账失败（不影响业务）：{exc}")


async def list_calls(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    feature: str | None = None,
    job_id: int | None = None,
    status: str | None = None,
) -> tuple[list[AiCall], int]:
    conditions = []
    if feature:
        conditions.append(AiCall.feature == feature)
    if job_id:
        conditions.append(AiCall.job_id == job_id)
    if status:
        conditions.append(AiCall.status == status)

    total = (
        await db.execute(select(func.count()).select_from(AiCall).where(*conditions))
    ).scalar_one()

    rows = (
        await db.execute(
            select(AiCall)
            .where(*conditions)
            .order_by(AiCall.create_time.desc(), AiCall.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), int(total)


def _month_start() -> datetime:
    now = utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _today_start() -> datetime:
    now = utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


async def _sum_cost(db: AsyncSession, since: datetime | None = None) -> float:
    query = select(func.coalesce(func.sum(AiCall.cost), 0))
    if since is not None:
        query = query.where(AiCall.create_time >= since)
    value = (await db.execute(query)).scalar_one()
    return float(value or 0)


async def summary(db: AsyncSession) -> dict:
    """成本汇总：总量、今日/本月、按功能、按职位、预算告警"""
    total_calls = (
        await db.execute(select(func.count()).select_from(AiCall))
    ).scalar_one()
    total_tokens = (
        await db.execute(select(func.coalesce(func.sum(AiCall.total_tokens), 0)))
    ).scalar_one()
    total_cost = await _sum_cost(db)
    today_cost = await _sum_cost(db, _today_start())
    month_cost = await _sum_cost(db, _month_start())

    by_feature_rows = (
        await db.execute(
            select(
                AiCall.feature,
                func.count().label("calls"),
                func.coalesce(func.sum(AiCall.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(AiCall.cost), 0).label("cost"),
            )
            .group_by(AiCall.feature)
            .order_by(func.coalesce(func.sum(AiCall.cost), 0).desc())
        )
    ).all()

    by_job_rows = (
        await db.execute(
            select(
                AiCall.job_id,
                func.count().label("calls"),
                func.coalesce(func.sum(AiCall.total_tokens), 0).label("tokens"),
                func.coalesce(func.sum(AiCall.cost), 0).label("cost"),
            )
            .where(AiCall.job_id.is_not(None))
            .group_by(AiCall.job_id)
            .order_by(func.coalesce(func.sum(AiCall.cost), 0).desc())
            .limit(10)
        )
    ).all()

    job_ids = {row.job_id for row in by_job_rows if row.job_id}
    job_titles: dict[int, str] = {}
    if job_ids:
        jobs = (
            await db.execute(select(Job.id, Job.title).where(Job.id.in_(job_ids)))
        ).all()
        job_titles = {job_id: title for job_id, title in jobs}

    budget = float(settings.MONTHLY_BUDGET_CNY or 0)
    ratio = round(month_cost / budget, 4) if budget > 0 else 0.0
    if budget <= 0:
        budget_status = "disabled"
    elif ratio >= 1:
        budget_status = "exceeded"
    elif ratio >= 0.8:
        budget_status = "warning"
    else:
        budget_status = "ok"

    return {
        "total_calls": int(total_calls),
        "total_tokens": int(total_tokens or 0),
        "total_cost": round(total_cost, 6),
        "today_cost": round(today_cost, 6),
        "month_cost": round(month_cost, 6),
        "budget": budget,
        "budget_ratio": ratio,
        "budget_status": budget_status,
        "by_feature": [
            {
                "feature": row.feature,
                "calls": int(row.calls),
                "tokens": int(row.tokens or 0),
                "cost": round(float(row.cost or 0), 6),
            }
            for row in by_feature_rows
        ],
        "top_jobs": [
            {
                "job_id": row.job_id,
                "job_title": job_titles.get(row.job_id) or f"职位#{row.job_id}",
                "calls": int(row.calls),
                "tokens": int(row.tokens or 0),
                "cost": round(float(row.cost or 0), 6),
            }
            for row in by_job_rows
        ],
    }
