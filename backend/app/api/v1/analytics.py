"""数据分析与成本监控接口"""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import CurrentUser, DbSession
from app.models.job import Job
from app.schemas.analytics import (
    AiCallListOut,
    AiCallOut,
    CostSummaryOut,
    DashboardOut,
    SlaOut,
)
from app.services import analytics as analytics_svc
from app.services import costs as cost_svc
from app.services import reports as report_svc

router = APIRouter(tags=["数据分析与成本"])


@router.get(
    "/analytics/dashboard",
    response_model=DashboardOut,
    summary="招聘数据看板（指标 + 漏斗 + 渠道 + 周期）",
)
async def dashboard_api(db: DbSession, _: CurrentUser) -> DashboardOut:
    return DashboardOut(**await analytics_svc.dashboard(db))


@router.get(
    "/analytics/sla",
    response_model=SlaOut,
    summary="SLA 超时监控（RA-04）",
)
async def sla_api(db: DbSession, _: CurrentUser) -> SlaOut:
    return SlaOut(**await analytics_svc.sla(db))


@router.get("/analytics/export", summary="导出招聘数据报表（Excel，DA-05）")
async def export_api(db: DbSession, _: CurrentUser) -> Response:
    content = await report_svc.build_workbook(db)
    filename = f"talentmatch-report-{datetime.now():%Y%m%d%H%M}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.get("/costs/summary", response_model=CostSummaryOut, summary="成本汇总与预算告警")
async def cost_summary_api(db: DbSession, _: CurrentUser) -> CostSummaryOut:
    return CostSummaryOut(**await cost_svc.summary(db))


@router.get("/costs", response_model=AiCallListOut, summary="AI 调用明细分页")
async def cost_list_api(
    db: DbSession,
    _: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    feature: str | None = Query(default=None, max_length=50),
    job_id: int | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(success|failed|skipped)$"),
) -> AiCallListOut:
    rows, total = await cost_svc.list_calls(
        db,
        page=page,
        page_size=page_size,
        feature=feature,
        job_id=job_id,
        status=status,
    )
    items = await _with_job_titles(db, rows)
    return AiCallListOut(items=items, total=total, page=page, page_size=page_size)


async def _with_job_titles(db: AsyncSession, rows) -> list[AiCallOut]:
    job_ids = {row.job_id for row in rows if row.job_id}
    titles: dict[int, str] = {}
    if job_ids:
        jobs = (
            await db.execute(select(Job.id, Job.title).where(Job.id.in_(job_ids)))
        ).all()
        titles = {job_id: title for job_id, title in jobs}

    items: list[AiCallOut] = []
    for row in rows:
        item = AiCallOut.model_validate(row)
        items.append(item.model_copy(update={"job_title": titles.get(row.job_id)}))
    return items
