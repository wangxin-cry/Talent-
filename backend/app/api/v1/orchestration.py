"""多 Agent 编排接口（阶段九）：执行编排 + 轨迹查询"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.agents import (
    OrchestrationError,
    get_trace,
    intent_table,
    list_recent_traces,
    run_orchestration,
)
from app.core.deps import CurrentUser, DbSession
from app.schemas.orchestration import (
    IntentListOut,
    OrchestrationRunIn,
    OrchestrationRunOut,
    TraceDetailOut,
    TraceListOut,
)

router = APIRouter(prefix="/orchestration", tags=["多 Agent 编排"])


@router.get("/intents", response_model=IntentListOut, summary="意图 → 子 Agent 映射表")
async def intents_api(_: CurrentUser) -> IntentListOut:
    return IntentListOut(items=intent_table())


@router.post(
    "/run",
    response_model=OrchestrationRunOut,
    summary="执行一次编排（返回结果 + 轨迹 + 总成本）",
)
async def run_api(
    payload: OrchestrationRunIn, db: DbSession, user: CurrentUser
) -> OrchestrationRunOut:
    try:
        data = await run_orchestration(db, payload, user.id)
    except OrchestrationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    return OrchestrationRunOut(**data)


@router.get("/traces", response_model=TraceListOut, summary="最近的编排轨迹")
async def traces_api(
    db: DbSession,
    _: CurrentUser,
    limit: int = Query(default=20, ge=1, le=100),
) -> TraceListOut:
    items = await list_recent_traces(db, limit=limit)
    return TraceListOut(items=items, total=len(items))


@router.get(
    "/traces/{trace_id}",
    response_model=TraceDetailOut,
    summary="单次编排的完整轨迹",
)
async def trace_detail_api(
    trace_id: str, db: DbSession, _: CurrentUser
) -> TraceDetailOut:
    data = await get_trace(db, trace_id)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="编排轨迹不存在"
        )
    return TraceDetailOut(**data)
