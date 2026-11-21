"""Manager / Supervisor 编排层（LangGraph）

结构：中心调度节点（supervisor）+ 6 个子 Agent 节点 + 条件路由边。
- Supervisor 只负责「按意图选步骤」，业务执行仍在各子 Agent；
- 每步失败/超时按三级降级处理，并写入 AgentTrace；
- Context Bus 让下游直接复用上游产出（匹配缺口 → 面试题）。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TypedDict

from fastapi import HTTPException
from langgraph.graph import END, StateGraph
from loguru import logger
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import subagents
from app.agents.context import OrchestrationContext, StepRecord
from app.agents.subagents import AgentOutcome, DependencyMissing
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import sha256_hex
from app.models.agent_trace import (
    AGENT_ANALYTICS,
    AGENT_INTERVIEW,
    AGENT_JD_WRITER,
    AGENT_MANAGER,
    AGENT_MATCH_ENGINE,
    AGENT_RESUME_PARSER,
    AGENT_WORKFLOW,
    TRACE_DEGRADED,
    TRACE_FAILED,
    TRACE_SKIPPED,
    TRACE_SUCCESS,
    TRACE_TIMEOUT,
    AgentTrace,
)
from app.models.ai_call import AiCall
from app.models.application import Application
from app.schemas.orchestration import OrchestrationRunIn


class OrchestrationError(ValueError):
    """参数缺失 / 意图不支持（API 层转 400）"""


# ---------------------------------------------------------------- 意图映射表
INTENT_MAP: dict[str, dict] = {
    "jd_generate": {
        "label": "生成 / 优化 JD",
        "agents": [AGENT_JD_WRITER],
        "description": "职位名 + 关键词 → 可编辑的三段 JD",
    },
    "resume_upload": {
        "label": "批量解析简历",
        "agents": [AGENT_RESUME_PARSER],
        "description": "逐份解析，单份失败不影响整批",
    },
    "match": {
        "label": "智能匹配",
        "agents": [AGENT_MATCH_ENGINE],
        "description": "规则算分 + 排名 + 可解释理由",
    },
    "interview": {
        "label": "生成面试题",
        "agents": [AGENT_INTERVIEW],
        "description": "基于匹配缺口的个性化面试题",
    },
    "advance_status": {
        "label": "推进状态",
        "agents": [AGENT_WORKFLOW],
        "description": "状态机校验 + 通知措辞",
    },
    "analytics": {
        "label": "看板洞察",
        "agents": [AGENT_ANALYTICS],
        "description": "统计数字 → 人话洞察",
    },
    "full_eval": {
        "label": "一键评估 top-N",
        "agents": [AGENT_MATCH_ENGINE, AGENT_INTERVIEW],
        "description": "匹配 → 取 top-N → 逐人生成面试题 + 轨迹 + 总成本",
    },
}

# 子 Agent 节点 → 实现函数名（运行时通过 getattr 查找，便于测试替换）
AGENT_FUNCTIONS = {
    AGENT_JD_WRITER: "run_jd_writer",
    AGENT_RESUME_PARSER: "run_resume_parser",
    AGENT_MATCH_ENGINE: "run_match_engine",
    AGENT_INTERVIEW: "run_interview_assistant",
    AGENT_WORKFLOW: "run_workflow_auto",
    AGENT_ANALYTICS: "run_analytics",
}
AGENT_FALLBACKS = {
    AGENT_JD_WRITER: "fallback_jd",
    AGENT_RESUME_PARSER: "fallback_resume",
    AGENT_MATCH_ENGINE: "fallback_match",
    AGENT_INTERVIEW: "fallback_interview",
    AGENT_WORKFLOW: "fallback_workflow",
    AGENT_ANALYTICS: "fallback_analytics",
}
# ai_call.agent 的实际写法
AI_AGENT_NAMES = {
    AGENT_JD_WRITER: "JDWriterAgent",
    AGENT_RESUME_PARSER: "ResumeParserAgent",
    AGENT_MATCH_ENGINE: "MatchEngineAgent",
    AGENT_INTERVIEW: "InterviewAssistantAgent",
    AGENT_WORKFLOW: "WorkflowAutoAgent",
    AGENT_ANALYTICS: "AnalyticsAgent",
}


class _State(TypedDict, total=False):
    ctx: OrchestrationContext
    next: str


# ---------------------------------------------------------------- 校验与入口
def _validate(payload: OrchestrationRunIn) -> None:
    intent = payload.intent
    if intent not in INTENT_MAP:
        raise OrchestrationError(
            f"未知意图：{intent}；可选：{'、'.join(INTENT_MAP)}"
        )
    if intent in ("full_eval", "match") and not payload.job_id:
        raise OrchestrationError("该意图需要 job_id")
    if intent == "advance_status" and (not payload.application_id or not payload.to_status):
        raise OrchestrationError("推进状态需要 application_id 与 to_status")
    if intent == "interview" and not (payload.application_id or payload.candidate_id):
        raise OrchestrationError("生成面试题需要 application_id 或 candidate_id")
    if intent == "jd_generate" and not (payload.title or payload.job_id):
        raise OrchestrationError("生成 JD 需要 title 或 job_id")


async def run_orchestration(
    db: AsyncSession, payload: OrchestrationRunIn, user_id: int
) -> dict:
    """执行一次编排，返回排名/结果 + 轨迹 + 成本"""
    _validate(payload)

    job_id = payload.job_id
    candidate_id = payload.candidate_id
    if payload.intent == "interview" and payload.application_id:
        application = await db.get(Application, payload.application_id)
        if application is None:
            raise OrchestrationError("应聘记录不存在")
        job_id = job_id or application.job_id
        candidate_id = candidate_id or application.candidate_id

    ctx = OrchestrationContext(
        trace_id=uuid.uuid4().hex,
        intent=payload.intent,
        user_id=user_id,
        job_id=job_id,
        application_id=payload.application_id,
        candidate_id=candidate_id,
        file_ids=list(payload.file_ids),
        to_status=payload.to_status,
        note=payload.note,
        offer_salary=payload.offer_salary,
        top_n=payload.top_n,
        limit=payload.limit,
        use_llm=payload.use_llm,
        step_timeout=payload.step_timeout or settings.ORCH_STEP_TIMEOUT_SECONDS,
        title=payload.title,
        department=payload.department,
        location=payload.location,
        keywords=list(payload.keywords),
        plan=list(INTENT_MAP[payload.intent]["agents"]),
    )

    # 第 0 步：Manager 拆解计划
    ctx.add_step(
        StepRecord(
            step_no=ctx.next_step_no(),
            agent=AGENT_MANAGER,
            input_summary={
                "intent": ctx.intent,
                "job_id": ctx.job_id,
                "application_id": ctx.application_id,
                "candidate_id": ctx.candidate_id,
                "top_n": ctx.top_n,
                "use_llm": ctx.use_llm,
                "files": len(ctx.file_ids),
            },
            output_summary={"plan": ctx.plan},
        )
    )

    graph = _build_graph(db)
    await graph.ainvoke(
        {"ctx": ctx, "next": END}, config={"recursion_limit": len(ctx.plan) * 2 + 6}
    )

    await _attach_usage(ctx)
    result = _build_result(ctx)
    status = TRACE_DEGRADED if ctx.degraded else TRACE_SUCCESS

    # 最后一步：Manager 聚合
    ctx.add_step(
        StepRecord(
            step_no=ctx.next_step_no(),
            agent=AGENT_MANAGER,
            status=status,
            degraded=ctx.degraded,
            duration_ms=ctx.duration_ms,
            output_summary={
                "status": status,
                "degraded": ctx.degraded,
                "duration_ms": ctx.duration_ms,
                "total_cost": round(sum(step.cost for step in ctx.steps), 6),
                "total_tokens": sum(
                    step.tokens_in + step.tokens_out for step in ctx.steps
                ),
                "errors": ctx.errors[:5],
            },
        )
    )

    await _persist_traces(db, ctx)

    total_tokens = sum(step.tokens_in + step.tokens_out for step in ctx.steps)
    total_cost = round(sum(step.cost for step in ctx.steps), 6)
    return {
        "trace_id": ctx.trace_id,
        "intent": ctx.intent,
        "intent_label": INTENT_MAP[ctx.intent]["label"],
        "status": status,
        "degraded": ctx.degraded,
        "duration_ms": ctx.duration_ms,
        "total_tokens": total_tokens,
        "total_cost": total_cost,
        "plan": ctx.plan,
        "steps": [_step_dict(step) for step in ctx.steps],
        "result": result,
    }


# ---------------------------------------------------------------- LangGraph
def _build_graph(db: AsyncSession):
    graph = StateGraph(_State)
    graph.add_node("supervisor", _supervisor_node)

    for agent in AGENT_FUNCTIONS:
        graph.add_node(agent, _make_agent_node(db, agent))
        graph.add_edge(agent, "supervisor")

    graph.set_entry_point("supervisor")
    routes = {agent: agent for agent in AGENT_FUNCTIONS}
    routes[END] = END
    graph.add_conditional_edges("supervisor", lambda state: state["next"], routes)
    return graph.compile()


def _supervisor_node(state: _State) -> dict:
    """中心调度：按计划推进；依赖缺失时记 skipped 并继续"""
    ctx = state["ctx"]
    while ctx.cursor < len(ctx.plan):
        agent = ctx.plan[ctx.cursor]
        ctx.cursor += 1

        if agent == AGENT_INTERVIEW and not ctx.match_results and not ctx.candidate_id:
            ctx.add_step(
                StepRecord(
                    step_no=ctx.next_step_no(),
                    agent=AGENT_INTERVIEW,
                    status=TRACE_SKIPPED,
                    degraded=True,
                    input_summary={"reason": "dependency_missing"},
                    error_reason="缺少上游匹配结果（依赖缺失），已跳过面试题",
                )
            )
            continue
        return {"next": agent}
    return {"next": END}


def _make_agent_node(db: AsyncSession, agent: str):
    async def node(state: _State) -> dict:
        await execute_step(db, state["ctx"], agent)
        return {"ctx": state["ctx"]}

    node.__name__ = f"node_{agent}"
    return node


async def execute_step(
    db: AsyncSession, ctx: OrchestrationContext, agent: str
) -> None:
    """执行单步：超时 / 失败 / 依赖缺失分别降级，并记录轨迹"""
    step = StepRecord(
        step_no=ctx.next_step_no(),
        agent=agent,
        input_summary=_step_input(ctx, agent),
    )
    started = time.perf_counter()
    fn = getattr(subagents, AGENT_FUNCTIONS[agent])

    try:
        outcome: AgentOutcome = await asyncio.wait_for(fn(db, ctx), timeout=ctx.step_timeout)
        step.status = TRACE_DEGRADED if outcome.degraded else TRACE_SUCCESS
        step.degraded = outcome.degraded
        step.error_reason = outcome.error
    except asyncio.TimeoutError:
        reason = f"执行超时（>{ctx.step_timeout:g}s）"
        outcome = await _run_fallback(db, ctx, agent, reason)
        step.status = TRACE_TIMEOUT
        step.degraded = True
        step.error_reason = outcome.error or reason
    except DependencyMissing as exc:
        step.status = TRACE_SKIPPED
        step.degraded = True
        step.error_reason = str(exc)
        outcome = AgentOutcome(summary={"skipped": True}, degraded=True, error=str(exc))
    except HTTPException as exc:
        # 业务拒绝（如非法状态迁移）：保留状态机结论，不当作系统故障
        outcome = await _run_fallback(db, ctx, agent, str(exc.detail))
        step.status = TRACE_DEGRADED
        step.degraded = True
        step.error_reason = str(exc.detail)
    except Exception as exc:  # noqa: BLE001
        reason = f"{type(exc).__name__}: {exc}"
        logger.warning(f"编排步骤失败 agent={agent}：{reason}")
        outcome = await _run_fallback(db, ctx, agent, reason)
        step.status = TRACE_FAILED
        step.degraded = True
        step.error_reason = outcome.error or reason

    step.duration_ms = int((time.perf_counter() - started) * 1000)
    step.output_summary = outcome.summary or {}
    ctx.add_step(step)


async def _run_fallback(
    db: AsyncSession, ctx: OrchestrationContext, agent: str, reason: str
) -> AgentOutcome:
    fallback = getattr(subagents, AGENT_FALLBACKS[agent])
    try:
        return await fallback(db, ctx, reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"兜底逻辑失败 agent={agent}：{exc}")
        return AgentOutcome(summary={"fallback_failed": True}, degraded=True, error=reason)


def _step_input(ctx: OrchestrationContext, agent: str) -> dict:
    if agent == AGENT_MATCH_ENGINE:
        return {"job_id": ctx.job_id, "use_llm": ctx.use_llm}
    if agent == AGENT_INTERVIEW:
        return {
            "job_id": ctx.job_id,
            "candidates": ctx.top_candidate_ids() or ([ctx.candidate_id] if ctx.candidate_id else []),
            "use_llm": ctx.use_llm,
        }
    if agent == AGENT_WORKFLOW:
        return {"application_id": ctx.application_id, "to_status": ctx.to_status}
    if agent == AGENT_RESUME_PARSER:
        return {"files": len(ctx.file_ids), "limit": ctx.limit}
    if agent == AGENT_JD_WRITER:
        return {"title": ctx.title, "job_id": ctx.job_id, "keywords": ctx.keywords}
    return {"intent": ctx.intent}


# ---------------------------------------------------------------- 成本归属与落库
async def _attach_usage(ctx: OrchestrationContext) -> None:
    """把本次 trace 的 ai_call 用量按 Agent 归属到对应步骤"""
    try:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(
                        AiCall.agent,
                        func.coalesce(func.sum(AiCall.input_tokens), 0),
                        func.coalesce(func.sum(AiCall.output_tokens), 0),
                        func.coalesce(func.sum(AiCall.cost), 0),
                    )
                    .where(AiCall.trace_id == ctx.trace_id)
                    .group_by(AiCall.agent)
                )
            ).all()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"编排用量汇总失败：{exc}")
        return

    usage = {
        row[0]: (int(row[1] or 0), int(row[2] or 0), float(row[3] or 0)) for row in rows
    }
    for step in ctx.steps:
        ai_agent = AI_AGENT_NAMES.get(step.agent)
        if ai_agent and ai_agent in usage:
            step.tokens_in, step.tokens_out, step.cost = usage[ai_agent]


async def _persist_traces(db: AsyncSession, ctx: OrchestrationContext) -> None:
    try:
        for step in ctx.steps:
            input_summary = step.input_summary or {}
            db.add(
                AgentTrace(
                    trace_id=ctx.trace_id,
                    step_no=step.step_no,
                    agent=step.agent,
                    parent_step=step.parent_step,
                    intent=ctx.intent,
                    input_summary=input_summary,
                    input_hash=sha256_hex(
                        json.dumps(input_summary, ensure_ascii=False, sort_keys=True, default=str)
                    ),
                    output_summary=step.output_summary or {},
                    status=step.status,
                    degraded=step.degraded,
                    error_reason=(step.error_reason or "")[:1000] or None,
                    duration_ms=step.duration_ms,
                    tokens_in=step.tokens_in,
                    tokens_out=step.tokens_out,
                    cost=step.cost,
                    tool_calls=step.tool_calls or [],
                )
            )
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"编排轨迹落库失败：{exc}")
        await db.rollback()


def _build_result(ctx: OrchestrationContext) -> dict:
    intent = ctx.intent
    if intent == "full_eval":
        return {
            "job": ctx.job_snapshot,
            "ranking": ctx.match_results[: ctx.top_n],
            "evaluations": ctx.artifacts.get("evaluations") or [],
            "errors": ctx.errors,
        }
    if intent == "match":
        return {
            "job": ctx.job_snapshot,
            "ranking": ctx.match_results,
            "errors": ctx.errors,
        }
    if intent == "interview":
        return {
            "evaluations": ctx.artifacts.get("evaluations") or [],
            "errors": ctx.errors,
        }
    if intent == "resume_upload":
        return ctx.artifacts.get(
            "resume_batch", {"total": 0, "success": 0, "failed": 0, "items": []}
        )
    if intent == "jd_generate":
        return ctx.artifacts.get("jd") or {}
    return ctx.result or {}


def _step_dict(step: StepRecord) -> dict:
    return {
        "step_no": step.step_no,
        "agent": step.agent,
        "parent_step": step.parent_step,
        "status": step.status,
        "degraded": step.degraded,
        "duration_ms": step.duration_ms,
        "tokens_in": step.tokens_in,
        "tokens_out": step.tokens_out,
        "cost": round(step.cost, 6),
        "input_summary": step.input_summary or {},
        "output_summary": step.output_summary or {},
        "error_reason": step.error_reason,
    }


# ---------------------------------------------------------------- 轨迹查询
def intent_table() -> list[dict]:
    return [
        {
            "intent": key,
            "label": value["label"],
            "agents": value["agents"],
            "description": value["description"],
        }
        for key, value in INTENT_MAP.items()
    ]


def _row_dict(row: AgentTrace) -> dict:
    return {
        "step_no": row.step_no,
        "agent": row.agent,
        "parent_step": row.parent_step,
        "status": row.status,
        "degraded": bool(row.degraded),
        "duration_ms": row.duration_ms or 0,
        "tokens_in": row.tokens_in or 0,
        "tokens_out": row.tokens_out or 0,
        "cost": float(row.cost or 0),
        "input_summary": row.input_summary or {},
        "output_summary": row.output_summary or {},
        "error_reason": row.error_reason,
    }


async def list_recent_traces(db: AsyncSession, limit: int = 20) -> list[dict]:
    """最近 N 次编排（按 trace 聚合）"""
    recent = (
        await db.execute(
            select(AgentTrace.trace_id, func.max(AgentTrace.create_time).label("created"))
            .group_by(AgentTrace.trace_id)
            .order_by(func.max(AgentTrace.create_time).desc())
            .limit(limit)
        )
    ).all()
    trace_ids = [row.trace_id for row in recent]
    if not trace_ids:
        return []

    rows = (
        await db.execute(
            select(
                AgentTrace.trace_id,
                func.max(AgentTrace.intent).label("intent"),
                # PostgreSQL 没有 max(boolean)，必须先用 CASE 转成 0/1 再聚合；
                # SQLite 恰好支持 max(0/1)，所以只有真实 PG 才暴露这个错误。
                func.max(
                    case((AgentTrace.degraded.is_(True), 1), else_=0)
                ).label("degraded"),
                func.coalesce(func.sum(AgentTrace.cost), 0).label("cost"),
                func.count().label("step_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (AgentTrace.agent != AGENT_MANAGER, AgentTrace.duration_ms),
                            else_=0,
                        )
                    ),
                    0,
                ).label("duration_ms"),
                func.max(AgentTrace.create_time).label("created"),
            )
            .where(AgentTrace.trace_id.in_(trace_ids))
            .group_by(AgentTrace.trace_id)
        )
    ).all()

    items = [
        {
            "trace_id": row.trace_id,
            "intent": row.intent,
            "status": TRACE_DEGRADED if row.degraded else TRACE_SUCCESS,
            "degraded": bool(row.degraded),
            "duration_ms": int(row.duration_ms or 0),
            "total_cost": round(float(row.cost or 0), 6),
            "step_count": int(row.step_count or 0),
            "create_time": row.created,
        }
        for row in rows
    ]
    items.sort(key=lambda item: item["create_time"], reverse=True)
    return items


async def get_trace(db: AsyncSession, trace_id: str) -> dict | None:
    rows = (
        await db.execute(
            select(AgentTrace)
            .where(AgentTrace.trace_id == trace_id)
            .order_by(AgentTrace.step_no.asc(), AgentTrace.id.asc())
        )
    ).scalars().all()
    if not rows:
        return None

    manager_final = [
        row
        for row in rows
        if row.agent == AGENT_MANAGER
        and isinstance(row.output_summary, dict)
        and "duration_ms" in row.output_summary
    ]
    if manager_final:
        summary = manager_final[-1].output_summary
        duration_ms = int(summary.get("duration_ms") or 0)
        total_cost = float(summary.get("total_cost") or 0)
        total_tokens = int(summary.get("total_tokens") or 0)
    else:
        duration_ms = sum(
            row.duration_ms or 0 for row in rows if row.agent != AGENT_MANAGER
        )
        total_cost = sum(float(row.cost or 0) for row in rows)
        total_tokens = sum((row.tokens_in or 0) + (row.tokens_out or 0) for row in rows)

    degraded = any(row.degraded for row in rows)
    return {
        "trace_id": trace_id,
        "intent": rows[0].intent,
        "status": TRACE_DEGRADED if degraded else TRACE_SUCCESS,
        "degraded": degraded,
        "duration_ms": duration_ms,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 6),
        "steps": [_row_dict(row) for row in rows],
        "create_time": rows[-1].create_time,
    }
