"""六个子 Agent 的编排适配层

职责边界：
- 子 Agent 只做「理解/生成/规则调用」，不自己管理编排、不写轨迹；
- 每个函数返回 AgentOutcome（摘要 + 是否降级 + 错误），由 Supervisor 记录轨迹；
- 确定性能力（状态机、规则分、统计）仍走 services，绝不由 LLM 判断。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context import OrchestrationContext
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.candidate import RF_FAILED, RF_PENDING, Candidate, ResumeFile
from app.models.job import Job
from app.schemas.job import JDGenerateIn
from app.services import analytics as analytics_svc
from app.services import candidates as candidates_svc
from app.services import interview_questions as question_svc
from app.services import jd_writer
from app.services import matching as matching_svc
from app.services import pipeline
from app.services.job import get_job_or_404


class DependencyMissing(RuntimeError):
    """前置步骤缺失，当前步骤应跳过（三级降级中的第 3 级）"""


@dataclass
class AgentOutcome:
    summary: dict = field(default_factory=dict)
    degraded: bool = False
    error: str | None = None


async def _job_snapshot(db: AsyncSession, job_id: int) -> tuple[Job, dict]:
    job = await get_job_or_404(db, job_id)
    snapshot = {
        "id": job.id,
        "title": job.title,
        "department": job.department,
        "jd_version": job.jd_version,
        "min_years": float(job.min_years) if job.min_years is not None else None,
        "education_level": job.education_level,
    }
    return job, snapshot


def _match_item(match, candidate: Candidate | None) -> dict:
    features = (match.detail or {}).get("features") or {}
    return {
        "match_id": match.id,
        "candidate_id": match.candidate_id,
        "candidate_name": candidate.name if candidate else None,
        "score": float(match.score),
        "skill_score": float(match.skill_score or 0),
        "exp_score": float(match.exp_score or 0),
        "edu_score": float(match.edu_score or 0),
        "summary": match.summary,
        "matched_skills": list(match.matched_skills or []),
        "missing_skills": list(match.missing_skills or []),
        "missing_must": list(features.get("missing_must") or []),
        "years_gap": features.get("years_gap"),
    }


async def run_jd_writer(db: AsyncSession, ctx: OrchestrationContext) -> AgentOutcome:
    """JDWriter：职位名 + 关键词 → 三段 JD（可编辑草稿）"""
    title = (ctx.title or "").strip()
    if not title and ctx.job_id:
        job = await db.get(Job, ctx.job_id)
        title = job.title if job else ""
    if not title:
        raise DependencyMissing("缺少职位名称，无法生成 JD")

    result = await jd_writer.generate_jd(
        db,
        JDGenerateIn(
            title=title,
            department=ctx.department,
            location=ctx.location,
            keywords=ctx.keywords,
        ),
        user_id=ctx.user_id,
    )
    ctx.artifacts["jd"] = {
        "summary": result.summary,
        "description": result.description,
        "requirements": result.requirements,
        "skills": [skill.name for skill in result.skills],
        "must_have_skills": [skill.name for skill in result.must_have_skills],
        "ai_generated": result.ai_generated,
    }
    return AgentOutcome(
        summary={
            "title": title,
            "skills": len(result.skills),
            "ai_generated": result.ai_generated,
        },
        degraded=not result.ai_generated,
        error=None if result.ai_generated else (result.note or "LLM 不可用，已回退模板"),
    )


async def run_resume_parser(db: AsyncSession, ctx: OrchestrationContext) -> AgentOutcome:
    """ResumeParser：批量解析（逐份隔离，单份失败不影响整批）"""
    file_ids = list(ctx.file_ids)
    if not file_ids:
        limit = min(ctx.limit or settings.ORCH_BATCH_LIMIT, settings.ORCH_BATCH_LIMIT)
        file_ids = list(
            (
                await db.execute(
                    select(ResumeFile.id)
                    .where(ResumeFile.status.in_([RF_PENDING, RF_FAILED]))
                    .order_by(ResumeFile.id.asc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    if not file_ids:
        ctx.artifacts["resume_batch"] = {"total": 0, "success": 0, "failed": 0, "items": []}
        return AgentOutcome(summary={"total": 0, "success": 0, "failed": 0})

    semaphore = asyncio.Semaphore(max(1, settings.ORCH_MAX_PARALLEL))

    async def one(file_id: int) -> dict:
        async with semaphore:
            try:
                await asyncio.wait_for(
                    candidates_svc.run_parse_task(file_id, trace_id=ctx.trace_id),
                    timeout=ctx.step_timeout,
                )
            except asyncio.TimeoutError:
                return {"file_id": file_id, "status": "timeout", "error": "解析超时"}
            except Exception as exc:  # noqa: BLE001
                return {"file_id": file_id, "status": "failed", "error": str(exc)[:200]}

            async with SessionLocal() as session:
                row = await session.get(ResumeFile, file_id)
                if row is None:
                    return {"file_id": file_id, "status": "failed", "error": "文件不存在"}
                return {
                    "file_id": file_id,
                    "status": row.status,
                    "candidate_id": row.candidate_id,
                    "error": row.error_reason,
                }

    items = list(await asyncio.gather(*(one(file_id) for file_id in file_ids)))
    success = sum(1 for item in items if item["status"] == "success")
    failed = len(items) - success
    ctx.artifacts["resume_batch"] = {
        "total": len(items),
        "success": success,
        "failed": failed,
        "items": items,
    }
    reasons = [f"#{item['file_id']}：{item.get('error') or item['status']}" for item in items if item["status"] != "success"]
    return AgentOutcome(
        summary={"total": len(items), "success": success, "failed": failed},
        degraded=failed > 0,
        error="；".join(reasons[:5]) if failed else None,
    )


async def run_match_engine(db: AsyncSession, ctx: OrchestrationContext) -> AgentOutcome:
    """MatchEngine：规则算分 → 排名 → 缺口写入 Context Bus"""
    if not ctx.job_id:
        raise DependencyMissing("缺少职位 id，无法执行匹配")

    job, snapshot = await _job_snapshot(db, ctx.job_id)
    ctx.job_snapshot = snapshot

    run = await matching_svc.match_job(
        db, job, use_llm=ctx.use_llm, trace_id=ctx.trace_id
    )

    candidate_ids = [row.candidate_id for row in run.items]
    candidates: dict[int, Candidate] = {}
    if candidate_ids:
        rows = (
            await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
        ).scalars().all()
        candidates = {row.id: row for row in rows}

    ctx.match_results = [_match_item(row, candidates.get(row.candidate_id)) for row in run.items]
    ctx.artifacts["match"] = {
        "total": len(ctx.match_results),
        "cached": run.cached_count,
        "computed": run.computed_count,
        "top": ctx.match_results[: ctx.top_n],
    }
    return AgentOutcome(
        summary={
            "job_id": job.id,
            "total": len(ctx.match_results),
            "cached": run.cached_count,
            "computed": run.computed_count,
            "top3": [item["candidate_id"] for item in ctx.match_results[: ctx.top_n]],
        }
    )


async def run_interview_assistant(db: AsyncSession, ctx: OrchestrationContext) -> AgentOutcome:
    """InterviewAssistant：为 top-N（或指定候选人）生成面试题

    直接使用匹配步骤刚写入数据库的缺口（Context Bus），不再重算简历特征。
    """
    if not ctx.job_id:
        raise DependencyMissing("缺少职位 id，无法生成面试题")

    if ctx.match_results:
        targets = ctx.top_candidate_ids()
    elif ctx.candidate_id:
        targets = [ctx.candidate_id]
    else:
        raise DependencyMissing("缺少匹配结果或候选人，无法生成面试题")

    # 把总预算均分给每个候选人，单个卡住不会拖死其余人
    per_timeout = max(0.05, ctx.step_timeout / max(1, len(targets)))
    evaluations: list[dict] = []
    for candidate_id in targets:
        try:
            preview = await asyncio.wait_for(
                question_svc.preview_questions(
                    db,
                    ctx.job_id,
                    candidate_id,
                    use_llm=ctx.use_llm,
                    user_id=ctx.user_id,
                    trace_id=ctx.trace_id,
                ),
                timeout=per_timeout,
            )
            evaluations.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_name": preview.get("candidate_name"),
                    "status": "success",
                    "source": preview.get("source"),
                    "questions": preview.get("questions") or [],
                    "match_gaps": preview.get("match_gaps") or {},
                }
            )
        except asyncio.TimeoutError:
            evaluations.append(
                {
                    "candidate_id": candidate_id,
                    "status": "timeout",
                    "questions": [],
                    "error": "面试题生成超时",
                }
            )
        except Exception as exc:  # noqa: BLE001
            evaluations.append(
                {
                    "candidate_id": candidate_id,
                    "status": "failed",
                    "questions": [],
                    "error": str(exc)[:200],
                }
            )

    ctx.artifacts["evaluations"] = evaluations
    failed = [item for item in evaluations if item["status"] != "success"]
    return AgentOutcome(
        summary={
            "candidates": len(evaluations),
            "questions": sum(len(item["questions"]) for item in evaluations),
            "failed": len(failed),
        },
        degraded=bool(failed),
        error="；".join(
            f"候选人#{item['candidate_id']}：{item.get('error') or item['status']}"
            for item in failed
        )
        or None,
    )


async def run_workflow_auto(db: AsyncSession, ctx: OrchestrationContext) -> AgentOutcome:
    """WorkflowAuto：状态机校验（确定性）+ 通知措辞（模板优先）"""
    if not ctx.application_id:
        raise DependencyMissing("缺少应聘记录 id，无法推进状态")
    if not ctx.to_status:
        raise DependencyMissing("缺少目标状态")

    application = await pipeline.get_application_or_404(db, ctx.application_id)
    from_status = application.status
    detail = await pipeline.change_status(
        db,
        application,
        ctx.to_status,
        ctx.user_id,
        note=ctx.note,
        offer_salary=ctx.offer_salary,
    )
    ctx.result = {
        "application_id": detail.id,
        "from_status": from_status,
        "from_label": detail.status_label,
        "to_status": detail.status,
        "to_label": detail.status_label,
        "allowed": True,
        "candidate_name": detail.candidate_name,
    }
    return AgentOutcome(
        summary={"application_id": detail.id, "from": from_status, "to": detail.status}
    )


async def run_analytics(db: AsyncSession, ctx: OrchestrationContext) -> AgentOutcome:
    """Analytics：统计数字（确定性）+ 模板洞察"""
    data = await analytics_svc.dashboard(db)
    overview = data["overview"]
    insights = [
        f"当前在招职位 {overview['open_jobs']} 个，累计投递 {overview['total_applications']} 份",
        f"待面试 {overview['pending_interview']} 人，已入职 {overview['hired']} 人",
    ]
    if overview.get("avg_cycle_days") is not None:
        insights.append(f"平均招聘周期 {overview['avg_cycle_days']} 天")

    funnel = [row for row in data["funnel"] if row["count"]]
    if funnel:
        weakest = min(
            (row for row in funnel if row.get("conversion") is not None),
            key=lambda row: row["conversion"],
            default=None,
        )
        if weakest:
            insights.append(
                f"转化最弱环节：{weakest['label']}（{weakest['conversion'] * 100:.0f}%）"
            )

    ctx.artifacts["analytics"] = {
        "overview": overview,
        "funnel": data["funnel"],
        "channels": data["channels"],
        "insights": insights,
    }
    ctx.result = {"insights": insights, "overview": overview}
    return AgentOutcome(summary={"insights": len(insights)})


# ---------------------------------------------------------------- 兜底（降级）
async def fallback_match(db: AsyncSession, ctx: OrchestrationContext, reason: str) -> AgentOutcome:
    """匹配失败/超时：复用最近一次有效匹配结果，保证排名仍可返回"""
    await db.rollback()
    if not ctx.job_id:
        return AgentOutcome(summary={"total": 0}, degraded=True, error=reason)

    job = await db.get(Job, ctx.job_id)
    if job is None:
        return AgentOutcome(summary={"total": 0}, degraded=True, error=reason)

    rows = await matching_svc.get_match_results(db, job)
    candidate_ids = [row.candidate_id for row in rows]
    candidates: dict[int, Candidate] = {}
    if candidate_ids:
        candidates = {
            row.id: row
            for row in (
                await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
            ).scalars().all()
        }
    ctx.match_results = [_match_item(row, candidates.get(row.candidate_id)) for row in rows]
    ctx.artifacts["match"] = {
        "total": len(ctx.match_results),
        "cached": len(ctx.match_results),
        "computed": 0,
        "fallback": True,
    }
    return AgentOutcome(
        summary={"total": len(ctx.match_results), "fallback": True},
        degraded=True,
        error=f"{reason}；已复用已有匹配结果",
    )


async def fallback_interview(
    db: AsyncSession, ctx: OrchestrationContext, reason: str
) -> AgentOutcome:
    """面试题失败/超时：明确记录缺失，不阻塞排名返回"""
    ctx.artifacts.setdefault("evaluations", [])
    return AgentOutcome(
        summary={"candidates": 0, "questions": 0, "failed": True},
        degraded=True,
        error=f"{reason}；面试题已跳过",
    )


async def fallback_workflow(
    db: AsyncSession, ctx: OrchestrationContext, reason: str
) -> AgentOutcome:
    """推进失败：保留状态机给出的原因，返回 allowed=false 而不是抛 500"""
    detail = getattr(reason, "detail", None)
    text = str(detail or reason)
    ctx.result = {
        "application_id": ctx.application_id,
        "to_status": ctx.to_status,
        "allowed": False,
        "reason": text,
    }
    return AgentOutcome(summary={"allowed": False}, degraded=True, error=text)


async def fallback_analytics(
    db: AsyncSession, ctx: OrchestrationContext, reason: str
) -> AgentOutcome:
    """洞察失败：仍返回纯数字统计"""
    data = await analytics_svc.dashboard(db)
    ctx.result = {"insights": [], "overview": data["overview"]}
    return AgentOutcome(
        summary={"insights": 0, "fallback": True}, degraded=True, error=reason
    )


async def fallback_jd(db: AsyncSession, ctx: OrchestrationContext, reason: str) -> AgentOutcome:
    return AgentOutcome(summary={"ai_generated": False}, degraded=True, error=reason)


async def fallback_resume(
    db: AsyncSession, ctx: OrchestrationContext, reason: str
) -> AgentOutcome:
    ctx.artifacts.setdefault(
        "resume_batch", {"total": 0, "success": 0, "failed": 0, "items": []}
    )
    return AgentOutcome(summary={"total": 0, "success": 0, "failed": 0}, degraded=True, error=reason)
