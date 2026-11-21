"""
招聘数据分析（阶段七）

指标全部由数据库确定性计算，LLM 只用于文案（本阶段暂不需要）。
- overview：在招职位、投递数、待面试、平均招聘周期
- funnel：各状态当前人数与相邻阶段转化
- channels：渠道投递量 / 入职量 / 转化率
- cycle：各阶段平均停留时长
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import (
    APP_HIRED,
    APP_INTERVIEW,
    APP_NEW,
    APP_OFFER,
    APP_REJECTED,
    APP_SCREENING,
    APP_STATUSES,
    APP_STATUS_LABELS,
    Application,
    ApplicationStageHistory,
)
from app.models.base import utcnow
from app.models.job import STATUS_PUBLISHED, Job

# 正向漏斗阶段（不含淘汰）
FORWARD_STAGES = (APP_NEW, APP_SCREENING, APP_INTERVIEW, APP_OFFER, APP_HIRED)
CHANNEL_UNKNOWN = "未标注"


def _label(value: str) -> str:
    return APP_STATUS_LABELS.get(value, value)


async def _reached_counts(db: AsyncSession) -> dict[str, set[int]]:
    """
    每个阶段「到达过」的应聘记录集合

    漏斗口径必须用「到达过」而不是「当前停留」：
    候选人流转到下一阶段后，上一阶段人数不应该减少，否则漏斗不单调、
    转化率会算出 >100% 或凭空的 100%。

    数据来源：application_stage_history（每次流转一条）；
    用当前状态兜底，避免历史缺失导致漏计。
    """
    reached: dict[str, set[int]] = {}
    history_rows = (
        await db.execute(
            select(
                ApplicationStageHistory.application_id,
                ApplicationStageHistory.to_status,
            ).distinct()
        )
    ).all()
    for application_id, status_value in history_rows:
        if status_value:
            reached.setdefault(status_value, set()).add(application_id)

    current_rows = (
        await db.execute(select(Application.id, Application.status))
    ).all()
    for application_id, status_value in current_rows:
        if status_value:
            reached.setdefault(status_value, set()).add(application_id)
    return reached


async def overview(db: AsyncSession) -> dict:
    open_jobs = (
        await db.execute(
            select(func.count()).select_from(Job).where(Job.status == STATUS_PUBLISHED)
        )
    ).scalar_one()

    total_applications = (
        await db.execute(select(func.count()).select_from(Application))
    ).scalar_one()

    status_rows = (
        await db.execute(
            select(Application.status, func.count()).group_by(Application.status)
        )
    ).all()
    status_counts = {status: int(count) for status, count in status_rows}

    hired_rows = (
        await db.execute(
            select(Application.applied_at, Application.hired_at).where(
                Application.status == APP_HIRED,
                Application.hired_at.is_not(None),
            )
        )
    ).all()
    durations = [
        (hired_at - applied_at).total_seconds() / 86400
        for applied_at, hired_at in hired_rows
        if hired_at and applied_at and hired_at >= applied_at
    ]
    avg_cycle_days = round(sum(durations) / len(durations), 1) if durations else None

    return {
        "open_jobs": int(open_jobs),
        "total_applications": int(total_applications),
        "pending_interview": status_counts.get(APP_INTERVIEW, 0),
        "hired": status_counts.get(APP_HIRED, 0),
        "rejected": status_counts.get(APP_REJECTED, 0),
        "avg_cycle_days": avg_cycle_days,
        "status_counts": status_counts,
    }


async def funnel(db: AsyncSession) -> list[dict]:
    """
    招聘漏斗：每阶段「到达过」的人数（单调不增），并附当前停留人数

    count     = 到达过该阶段的应聘数（漏斗口径，来自流转历史）
    current   = 当前停留在该状态的人数（现状口径）
    conversion= 本阶段到达数 / 上一阶段到达数
    """
    current_rows = (
        await db.execute(
            select(Application.status, func.count()).group_by(Application.status)
        )
    ).all()
    current = {status: int(count) for status, count in current_rows}

    reached = await _reached_counts(db)
    total = sum(current.values()) or 0

    stages: list[dict] = []
    previous: int | None = None
    for stage in APP_STATUSES:
        count = len(reached.get(stage, ()))
        if stage in FORWARD_STAGES:
            conversion = round(count / previous, 4) if previous else None
            previous = count if count else previous
        else:
            conversion = None
        stages.append(
            {
                "status": stage,
                "label": _label(stage),
                "count": count,
                "current": current.get(stage, 0),
                "share": round(count / total, 4) if total else 0.0,
                "conversion": conversion,
            }
        )
    return stages


async def channels(db: AsyncSession) -> list[dict]:
    """
    渠道效果：投递数 / 到达面试数 / 入职数 / 淘汰数 / 入职转化率

    面试与入职同样按「到达过」统计，否则已入职的人不会被计入面试数。
    """
    rows = (
        await db.execute(select(Application.id, Application.source))
    ).all()
    reached = await _reached_counts(db)
    interview_ids = reached.get(APP_INTERVIEW, set())
    hired_ids = reached.get(APP_HIRED, set())
    rejected_ids = reached.get(APP_REJECTED, set())

    buckets: dict[str, dict] = {}
    for application_id, source in rows:
        key = (source or "").strip() or CHANNEL_UNKNOWN
        bucket = buckets.setdefault(
            key, {"source": key, "total": 0, "interview": 0, "hired": 0, "rejected": 0}
        )
        bucket["total"] += 1
        if application_id in interview_ids:
            bucket["interview"] += 1
        if application_id in hired_ids:
            bucket["hired"] += 1
        if application_id in rejected_ids:
            bucket["rejected"] += 1

    result = list(buckets.values())
    for bucket in result:
        bucket["conversion"] = (
            round(bucket["hired"] / bucket["total"], 4) if bucket["total"] else 0.0
        )
    result.sort(key=lambda item: (-item["total"], item["source"]))
    return result


async def cycle(db: AsyncSession) -> list[dict]:
    """各阶段平均停留时长（来自流转历史冗余字段）"""
    rows = (
        await db.execute(
            select(
                ApplicationStageHistory.from_status,
                func.count().label("samples"),
                func.coalesce(func.sum(ApplicationStageHistory.duration_in_prev_status), 0).label(
                    "total_seconds"
                ),
            )
            .where(
                ApplicationStageHistory.from_status.is_not(None),
                ApplicationStageHistory.duration_in_prev_status.is_not(None),
            )
            .group_by(ApplicationStageHistory.from_status)
        )
    ).all()

    by_stage = {
        row.from_status: (int(row.samples), int(row.total_seconds or 0)) for row in rows
    }

    result: list[dict] = []
    for stage in FORWARD_STAGES:
        samples, total_seconds = by_stage.get(stage, (0, 0))
        avg_hours = round(total_seconds / samples / 3600, 1) if samples else None
        result.append(
            {
                "stage": stage,
                "label": _label(stage),
                "samples": samples,
                "avg_hours": avg_hours,
            }
        )
    return result


async def dashboard(db: AsyncSession) -> dict:
    return {
        "overview": await overview(db),
        "funnel": await funnel(db),
        "channels": await channels(db),
        "cycle": await cycle(db),
        "generated_at": utcnow(),
    }
