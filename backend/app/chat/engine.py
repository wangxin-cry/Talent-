"""对话式入口核心引擎（阶段九½）

一轮对话的完整链路：
    意图识别 → 槽位抽取（含上下文推断）→ 缺参追问 → 三级安全闸 → 调 Supervisor / 服务 → 卡片

安全策略：
- read：直接执行；
- write（发布职位）：先出执行计划，确认后执行；
- irreversible（推进 / 淘汰）：强制确认卡，确认后才执行。
"""
from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from fastapi import HTTPException
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import OrchestrationError, run_orchestration
from app.chat import nlu
from app.models.application import (
    APP_REJECTED,
    APP_STATUS_LABELS,
    APP_TRANSITIONS,
)
from app.models.base import utcnow
from app.models.candidate import Candidate
from app.models.chat import (
    CARD_CHART,
    CARD_CONFIRM,
    CARD_INTERVIEW,
    CARD_MATCH_RANK,
    CARD_PARSE_RESULT,
    CARD_UPLOAD,
    ROLE_ASSISTANT,
    ROLE_USER,
    ChatMessage,
    ChatSession,
)
from app.models.job import Job
from app.models.user import ROLE_ADMIN, ROLE_MANAGER
from app.schemas.chat import ChatMessageOut, ChatSendIn, ChatSessionOut
from app.schemas.orchestration import OrchestrationRunIn
from app.services import analytics as analytics_svc
from app.services import candidates as candidates_svc
from app.services import job as job_svc
from app.services import pipeline

WELCOME_CHIPS = [
    {"label": "📥 我传了一批简历", "text": "我传了一批简历"},
    {"label": "🎯 看看谁适合后端岗", "text": "看看这批简历谁适合后端岗"},
    {"label": "💬 前三个出面试题", "text": "给前三个出面试题"},
    {"label": "📊 这个月渠道效率", "text": "这个月哪个渠道效率最高？"},
    {"label": "➡️ 把候选人推到面试", "text": "把这个候选人推到面试"},
]

CONFIRM_ACTIONS = {"advance_status", "reject_candidate", "publish_job", "submit_job"}

STATUS_TEXT = {
    "screening": "筛选中",
    "interview": "面试中",
    "offer": "Offer",
    "hired": "已入职",
    "rejected": "已淘汰",
}


# ---------------------------------------------------------------- 返回结构
@dataclass
class PlannedMessage:
    text: str | None = None
    card_type: str | None = None
    card_data: dict = field(default_factory=dict)
    trace_id: str | None = None
    tokens: int = 0
    cost: float = 0.0


@dataclass
class Execution:
    intent: str
    intent_label: str
    messages: list[PlannedMessage] = field(default_factory=list)
    trace_id: str | None = None
    degraded: bool = False
    duration_ms: int = 0
    total_cost: float = 0.0


# ---------------------------------------------------------------- 会话
def _session_out(db: AsyncSession, session: ChatSession, *, counts=None) -> ChatSessionOut:
    message_count, last_message = (counts or (0, None))
    return ChatSessionOut(
        id=session.id,
        title=session.title,
        context_job_id=session.context_job_id,
        context_candidate_id=session.context_candidate_id,
        last_message_at=session.last_message_at,
        create_time=session.create_time,
        update_time=session.update_time,
        message_count=message_count,
        last_message=last_message,
    )


async def session_payload(db: AsyncSession, session: ChatSession) -> ChatSessionOut:
    count = (
        await db.execute(
            select(func.count()).select_from(ChatMessage).where(
                ChatMessage.session_id == session.id
            )
        )
    ).scalar_one()
    last = (
        await db.execute(
            select(ChatMessage.content)
            .where(
                ChatMessage.session_id == session.id,
                ChatMessage.content.is_not(None),
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return _session_out(db, session, counts=(int(count), last))


async def session_payloads(
    db: AsyncSession, sessions: list[ChatSession]
) -> list[ChatSessionOut]:
    """
    批量组装会话列表（避免 N+1）

    早期实现对每个会话分别 COUNT + 取最后消息：50 个会话就是 100 次查询。
    这里改成两条聚合查询，整体只多 2 次。
    """
    if not sessions:
        return []

    ids = [row.id for row in sessions]

    count_rows = (
        await db.execute(
            select(ChatMessage.session_id, func.count().label("calls"))
            .where(ChatMessage.session_id.in_(ids))
            .group_by(ChatMessage.session_id)
        )
    ).all()
    counts = {row.session_id: int(row.calls) for row in count_rows}

    # 取每个会话最后一条有正文的消息：按 id 倒序取，首次出现的即为最新
    last_rows = (
        await db.execute(
            select(ChatMessage.session_id, ChatMessage.content)
            .where(
                ChatMessage.session_id.in_(ids),
                ChatMessage.content.is_not(None),
            )
            .order_by(ChatMessage.id.desc())
        )
    ).all()
    last_map: dict[int, str] = {}
    for row in last_rows:
        last_map.setdefault(row.session_id, row.content)

    return [
        _session_out(
            db,
            session,
            counts=(counts.get(session.id, 0), last_map.get(session.id)),
        )
        for session in sessions
    ]


def message_out(row: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=row.id,
        session_id=row.session_id,
        role=row.role,
        content=row.content,
        card_type=row.card_type,
        card_data=row.card_data or {},
        intent=row.intent,
        trace_id=row.trace_id,
        tokens=int(row.tokens or 0),
        cost=float(row.cost or 0),
        create_time=row.create_time,
    )


async def get_session_or_404(
    db: AsyncSession, session_id: int, user_id: int
) -> ChatSession:
    session = await db.get(ChatSession, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session


def _add_message(
    db: AsyncSession,
    session: ChatSession,
    role: str,
    *,
    content: str | None = None,
    card_type: str | None = None,
    card_data: dict | None = None,
    intent: str | None = None,
    trace_id: str | None = None,
    tokens: int = 0,
    cost: float = 0.0,
) -> ChatMessage:
    row = ChatMessage(
        session_id=session.id,
        role=role,
        content=content,
        card_type=card_type,
        card_data=card_data or {},
        intent=intent,
        trace_id=trace_id,
        tokens=tokens,
        cost=cost,
    )
    db.add(row)
    session.last_message_at = utcnow()
    return row


async def _history(db: AsyncSession, session_id: int, limit: int = 40) -> list[dict]:
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [
        {"role": row.role, "content": row.content or "", "card_type": row.card_type}
        for row in reversed(rows)
    ]


async def _latest_clarify(db: AsyncSession, session_id: int) -> ChatMessage | None:
    row = (
        await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == ROLE_ASSISTANT,
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or not isinstance(row.card_data, dict):
        return None
    if (row.card_data.get("clarify") or {}).get("resolved"):
        return None
    return row if row.card_data.get("clarify") else None


async def _mark_clarify_resolved(db: AsyncSession, row: ChatMessage) -> None:
    data = dict(row.card_data or {})
    clarify = dict(data.get("clarify") or {})
    clarify["resolved"] = True
    data["clarify"] = clarify
    row.card_data = data
    await db.flush()


# ---------------------------------------------------------------- 意图与槽位
async def _decide(
    db: AsyncSession,
    session: ChatSession,
    text: str,
    history: list[dict],
    use_llm: bool,
) -> nlu.Decision:
    intent, confidence = nlu.classify_intent(text)
    matched_by = "rule"
    slots = await nlu.extract_slots(db, text, session)

    if intent is None:
        llm_intent, llm_conf, llm_slots = await nlu.classify_with_llm(
            db, text, history, user_id=session.user_id
        )
        if llm_intent:
            intent, confidence, matched_by = llm_intent, llm_conf, "llm"
            slots = {**llm_slots, **slots}

    pending_row = await _latest_clarify(db, session.id)
    pending_failed = False
    pending_intent: str | None = None
    if pending_row is not None:
        pending = pending_row.card_data.get("clarify") or {}
        pending_intent = pending.get("intent")
        filled = await _fill_missing(db, session, pending.get("field"), text, slots)
        if filled is not None:
            intent = pending.get("intent") or intent
            confidence = max(confidence, 0.8)
            matched_by = "pending"
            slots = {**(pending.get("slots") or {}), **slots, **filled}
        else:
            await _mark_clarify_resolved(db, pending_row)
            pending_failed = True
            if intent is None:
                return nlu.Decision(intent=None, confidence=0.0, matched_by=matched_by)

    if intent is None:
        return nlu.Decision(intent=None, confidence=0.0, matched_by=matched_by)

    decision = nlu.Decision(
        intent=intent, confidence=confidence, matched_by=matched_by, slots=slots
    )
    await _check_requirements(db, session, decision, text)
    # 缺参只追问一次：**同一意图**上一轮已经问过且这次仍补不上，才退回能力清单，
    # 避免同一个问题反复追问。如果用户已经换了意图（如追问职位时改问匹配），
    # 应正常执行新请求，而不是把新意图也吞掉。
    if pending_failed and decision.missing and decision.intent == pending_intent:
        return nlu.Decision(intent=None, confidence=confidence, matched_by=matched_by, slots=slots)
    return decision


async def _fill_missing(
    db: AsyncSession,
    session: ChatSession,
    missing: str | None,
    text: str,
    slots: dict,
) -> dict | None:
    """用用户这一句补上刚才追问的槽位"""
    if not missing:
        return None
    if missing == "job":
        jobs = list(
            (await db.execute(select(Job).order_by(Job.id.desc()))).scalars().all()
        )
        job = nlu._match_job_in_text(jobs, text)
        return {"job_id": job.id, "job_title": job.title} if job else None
    if missing == "candidate":
        candidates = list(
            (
                await db.execute(
                    select(Candidate)
                    .where(Candidate.is_deleted.is_(False), Candidate.name.is_not(None))
                    .order_by(Candidate.id.desc())
                )
            ).scalars().all()
        )
        named = [row for row in candidates if row.name and row.name in text]
        if named:
            return {"candidate_id": named[0].id, "candidate_name": named[0].name}
        return None
    if missing == "title":
        cleaned = text.strip(" 的了，。,.!！?？")
        return {"title": cleaned} if 1 < len(cleaned) <= 40 else None
    if missing == "to_status":
        status = nlu._extract_status(text)
        return {"to_status": status} if status else None
    return None


async def _check_requirements(
    db: AsyncSession,
    session: ChatSession,
    decision: nlu.Decision,
    text: str,
) -> None:
    intent = decision.intent
    slots = decision.slots
    job_id = slots.get("job_id")
    candidate_id = slots.get("candidate_id")

    if intent in ("match", "interview", "advance_status", "reject_candidate") and not job_id:
        await _set_clarify(db, decision, "job", "用哪个职位来做这次操作？")
        return

    if intent in ("advance_status", "reject_candidate", "application_status"):
        if not candidate_id:
            await _set_clarify(db, decision, "candidate", "是哪位候选人？")
            return
        application_id = slots.get("application_id")
        if not application_id:
            application = await nlu.find_application(db, candidate_id, job_id)
            if application is None:
                decision.missing = "application"
                decision.clarify_question = (
                    f"{slots.get('candidate_name') or '该候选人'} 在"
                    f"「{slots.get('job_title') or '当前职位'}」还没有应聘记录，"
                    "请先到流程看板创建应聘记录。"
                )
                return
            slots["application_id"] = application.id
            slots["from_status"] = application.status

    if intent == "advance_status" and not slots.get("to_status"):
        await _set_clarify(
            db,
            decision,
            "to_status",
            "要推进到哪个阶段？（筛选中 / 面试中 / Offer / 已入职）",
        )
        return

    if intent in ("publish_job",) and not job_id:
        await _set_clarify(db, decision, "job", "要发布哪个职位？")
        return

    if intent == "jd_generate" and not (slots.get("title") or job_id):
        await _set_clarify(db, decision, "title", "要生成哪个职位的 JD？")
        return


async def _set_clarify(
    db: AsyncSession, decision: nlu.Decision, field: str, question: str
) -> None:
    decision.missing = field
    decision.clarify_question = question
    if field == "job":
        jobs = list(
            (
                await db.execute(
                    select(Job)
                    .where(Job.status.in_(["published", "draft", "pending"]))
                    .order_by(Job.id.desc())
                    .limit(6)
                )
            ).scalars().all()
        )
        if not jobs:
            decision.options = [
                {
                    "label": "去职位页创建职位",
                    "href": "/jobs",
                    "text": "当前没有可用职位，请先到职位页创建并发布职位。",
                }
            ]
        else:
            decision.options = [
                {"label": job.title, "job_id": job.id, "text": job.title} for job in jobs
            ]
    elif field == "candidate":
        candidates = list(
            (
                await db.execute(
                    select(Candidate)
                    .where(Candidate.is_deleted.is_(False), Candidate.name.is_not(None))
                    .order_by(Candidate.id.desc())
                    .limit(8)
                )
            ).scalars().all()
        )
        decision.options = [
            {"label": row.name or f"候选人{row.id}", "candidate_id": row.id, "text": row.name}
            for row in candidates
        ]
    elif field == "to_status":
        decision.options = [
            {"label": "筛选中", "text": "推进到筛选中"},
            {"label": "面试中", "text": "推进到面试中"},
            {"label": "Offer", "text": "推进到 Offer"},
            {"label": "已入职", "text": "推进到已入职"},
        ]


# ---------------------------------------------------------------- 主流程
Emit = Callable[[dict], Awaitable[None]]


async def _emit(emit: Emit | None, event: dict) -> None:
    """进度事件只用于展示，推送失败不能影响业务执行"""
    if emit is None:
        return
    try:
        await emit(event)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"对话进度事件推送失败：{exc}")


async def handle_message(
    db: AsyncSession,
    session: ChatSession,
    payload: ChatSendIn,
    user,
    emit: Emit | None = None,
) -> dict:
    started = time.perf_counter()
    if payload.context_job_id is not None:
        session.context_job_id = payload.context_job_id
    if payload.context_candidate_id is not None:
        session.context_candidate_id = payload.context_candidate_id

    await _emit(
        emit,
        {"type": "status", "stage": "classifying", "text": "正在理解你的需求…"},
    )
    history = await _history(db, session.id)
    decision = await _decide(db, session, payload.text, history, payload.use_llm)
    await _emit(
        emit,
        {
            "type": "intent",
            "intent": decision.intent,
            "label": nlu.INTENT_META.get(decision.intent or "", {}).get("label"),
            "needs_clarification": bool(decision.missing),
        },
    )

    user_row = _add_message(
        db,
        session,
        ROLE_USER,
        content=payload.text.strip(),
        intent=decision.intent,
    )
    if decision.slots.get("job_id"):
        session.context_job_id = decision.slots["job_id"]
    if decision.slots.get("candidate_id"):
        session.context_candidate_id = decision.slots["candidate_id"]

    if not session.title:
        title = payload.text.strip().replace("\n", " ")
        session.title = (title[:24] + "…") if len(title) > 24 else title

    # 先落盘：Supervisor 的兜底逻辑可能 rollback，不能把用户消息一起回滚
    await db.commit()
    await db.refresh(user_row)
    await db.refresh(session)

    replies: list[ChatMessage] = []
    execution: Execution | None = None

    if decision.missing == "application":
        replies.append(
            _add_message(
                db,
                session,
                ROLE_ASSISTANT,
                content=decision.clarify_question,
                card_data={"chips": WELCOME_CHIPS[:2]},
                intent=decision.intent,
            )
        )
    elif decision.missing:
        replies.append(
            _add_message(
                db,
                session,
                ROLE_ASSISTANT,
                content=decision.clarify_question,
                card_data={
                    "clarify": {
                        "field": decision.missing,
                        "intent": decision.intent,
                        "slots": decision.slots,
                        "question": decision.clarify_question,
                        "asked": True,
                        "resolved": False,
                    },
                    "options": decision.options,
                },
                intent=decision.intent,
            )
        )
    elif decision.intent is None:
        replies.append(
            _add_message(
                db,
                session,
                ROLE_ASSISTANT,
                content=(
                    "我可以帮你做这些事：解析简历、人才库检索、人岗匹配、生成面试题、"
                    "推进/淘汰候选人、生成 JD、查看看板数据。\n"
                    "也可以直接说：「把张伟推到面试」或「这个月哪个渠道效率最高」。"
                ),
                card_data={"chips": WELCOME_CHIPS},
            )
        )
    else:
        await _emit(
            emit,
            {
                "type": "status",
                "stage": "executing",
                "text": f"正在执行「{nlu.INTENT_META.get(decision.intent or '', {}).get('label') or '任务'}」…",
            },
        )
        try:
            execution = await _execute(db, session, decision, payload, user)
            for spec in execution.messages:
                replies.append(
                    _add_message(
                        db,
                        session,
                        ROLE_ASSISTANT,
                        content=spec.text,
                        card_type=spec.card_type,
                        card_data=spec.card_data,
                        intent=execution.intent,
                        trace_id=spec.trace_id or execution.trace_id,
                        tokens=spec.tokens,
                        cost=spec.cost,
                    )
                )
        except OrchestrationError as exc:
            replies.append(
                _add_message(
                    db,
                    session,
                    ROLE_ASSISTANT,
                    content=f"暂时无法执行：{exc}",
                    intent=decision.intent,
                )
            )
        except HTTPException as exc:
            replies.append(
                _add_message(
                    db,
                    session,
                    ROLE_ASSISTANT,
                    content=f"执行失败：{exc.detail}",
                    intent=decision.intent,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"对话执行失败 intent={decision.intent}：{exc}")
            replies.append(
                _add_message(
                    db,
                    session,
                    ROLE_ASSISTANT,
                    content="执行失败，请稍后重试；页面上的同名按钮仍然可用。",
                    intent=decision.intent,
                )
            )

    await _emit(emit, {"type": "status", "stage": "finalizing", "text": "正在整理结果…"})
    await db.commit()
    for row in [user_row, *replies]:
        await db.refresh(row)
    await db.refresh(session)

    label = nlu.INTENT_META.get(decision.intent or "", {}).get("label")
    return {
        "session": await session_payload(db, session),
        "user_message": message_out(user_row),
        "replies": [message_out(row) for row in replies],
        "intent": decision.intent,
        "intent_label": label,
        "confidence": decision.confidence,
        "needs_clarification": bool(decision.missing),
        "trace_id": execution.trace_id if execution else None,
        "degraded": execution.degraded if execution else False,
        "duration_ms": (
            execution.duration_ms
            if execution
            else int((time.perf_counter() - started) * 1000)
        ),
        "total_cost": execution.total_cost if execution else 0.0,
    }


# ---------------------------------------------------------------- 执行
async def _execute(
    db: AsyncSession,
    session: ChatSession,
    decision: nlu.Decision,
    payload: ChatSendIn,
    user,
) -> Execution:
    intent = decision.intent or ""
    slots = decision.slots
    meta = nlu.INTENT_META.get(intent, {})
    execution = Execution(intent=intent, intent_label=meta.get("label") or intent)

    if intent in ("advance_status", "reject_candidate", "publish_job"):
        execution.messages = await _build_confirm(db, session, decision, user)
        return execution

    if intent == "resume_upload":
        return await _run_resume_upload(db, decision, payload, user)

    if intent == "match":
        return await _run_match(db, decision, payload, user)

    if intent == "interview":
        return await _run_interview(db, decision, payload, user)

    if intent == "jd_generate":
        return await _run_jd(db, decision, payload, user)

    if intent == "analytics":
        return await _run_analytics(db, execution, payload, user)

    if intent == "search_candidates":
        return await _run_search(db, decision)

    if intent == "application_status":
        return await _run_application_status(db, decision)

    execution.messages = [
        PlannedMessage(text="我还没学会这个操作，可以先试试：匹配、出面试题、查数据。")
    ]
    return execution


def _orch_payload(intent: str, **kwargs) -> OrchestrationRunIn:
    return OrchestrationRunIn(intent=intent, **kwargs)


def _card_from_match(result: dict, top_n: int) -> tuple[str, dict]:
    ranking = result.get("ranking") or []
    job = result.get("job") or {}
    rows = []
    for index, item in enumerate(ranking[: max(1, top_n)], start=1):
        matched = list(item.get("matched_skills") or [])[:6]
        missing = list(item.get("missing_skills") or [])[:6]
        bits = []
        if matched:
            bits.append("命中 " + " · ".join(matched))
        if missing:
            bits.append("缺 " + " · ".join(missing))
        years_gap = item.get("years_gap")
        if item.get("experience") or years_gap is not None:
            bits.append(f"经验差 {years_gap}")
        rows.append(
            {
                "no": index,
                "candidate_id": item.get("candidate_id"),
                "name": item.get("candidate_name") or f"候选人{item.get('candidate_id')}",
                "score": round(float(item.get("score") or 0), 1),
                "sub": " ｜ ".join(bits) or "暂无技能明细",
                "reason": item.get("summary") or "",
                "matched_skills": matched,
                "missing_skills": missing,
                "years_gap": years_gap,
                "open": False,
            }
        )
    card = {
        "job_title": job.get("title") or "",
        "total": len(ranking),
        "ranks": rows,
        "chips": [
            {"label": "💬 前三个出面试题", "text": "给前三个出面试题"},
        ],
    }
    if rows:
        card["chips"].append(
            {
                "label": f"➡️ 把{rows[0]['name']}推到面试",
                "text": f"把{rows[0]['name']}推到面试",
            }
        )
    if rows:
        text = (
            f"已用「{card['job_title'] or '当前职位'}」完成匹配，共 {len(ranking)} 人。"
            f"最高分 {rows[0]['score']}（{rows[0]['name']}）。"
        )
    else:
        text = "没有可匹配的候选人，先上传并解析简历吧。"
    return text, card


async def _run_match(
    db: AsyncSession, decision: nlu.Decision, payload: ChatSendIn, user
) -> Execution:
    slots = decision.slots
    top_n = int(slots.get("top_n") or 10)
    data = await run_orchestration(
        db,
        _orch_payload(
            "match",
            job_id=slots.get("job_id"),
            top_n=min(top_n, 10),
            use_llm=payload.use_llm,
        ),
        user.id,
    )
    text, card = _card_from_match(data.get("result") or {}, top_n)
    if data.get("degraded"):
        text += "（部分步骤降级，已返回现有结果）"
    return Execution(
        intent="match",
        intent_label="智能匹配",
        messages=[
            PlannedMessage(
                text=text,
                card_type=CARD_MATCH_RANK,
                card_data=card,
                trace_id=data.get("trace_id"),
            )
        ],
        trace_id=data.get("trace_id"),
        degraded=bool(data.get("degraded")),
        duration_ms=int(data.get("duration_ms") or 0),
        total_cost=float(data.get("total_cost") or 0),
    )


async def _run_interview(
    db: AsyncSession, decision: nlu.Decision, payload: ChatSendIn, user
) -> Execution:
    slots = decision.slots
    top_n = int(slots.get("top_n") or 3)
    candidate_id = slots.get("candidate_id")
    if candidate_id:
        intent = "interview"
        data = await run_orchestration(
            db,
            _orch_payload(
                "interview",
                job_id=slots.get("job_id"),
                candidate_id=candidate_id,
                application_id=slots.get("application_id"),
                use_llm=payload.use_llm,
            ),
            user.id,
        )
    else:
        intent = "full_eval"
        data = await run_orchestration(
            db,
            _orch_payload(
                "full_eval",
                job_id=slots.get("job_id"),
                top_n=min(top_n, 10),
                use_llm=payload.use_llm,
            ),
            user.id,
        )

    result = data.get("result") or {}
    evaluations = result.get("evaluations") or []
    success = [item for item in evaluations if item.get("status") == "success"]
    total_questions = sum(len(item.get("questions") or []) for item in success)
    cost = float(data.get("total_cost") or 0)
    duration_ms = int(data.get("duration_ms") or 0)
    names = "、".join(
        str(item.get("candidate_name") or f"候选人{item.get('candidate_id')}")
        for item in success
    )
    summary = (
        f"已生成 {total_questions} 道面试题（{len(success)} 人：{names or '无'}），"
        f"耗时 {duration_ms / 1000:.1f}s，花费 ¥{cost:.4f}。"
    )
    if data.get("degraded"):
        summary += "（部分候选人未生成，可稍后重试）"

    messages = [
        PlannedMessage(
            text=summary,
            trace_id=data.get("trace_id"),
            tokens=int(data.get("total_tokens") or 0),
            cost=cost,
        )
    ]
    for item in success:
        questions = [
            {
                "cat": question.get("category") or question.get("cat") or "面试题",
                "q": question.get("question") or question.get("q") or "",
                "look": question.get("looking_for") or question.get("look") or "",
                "reference": question.get("reference") or "",
                "follow_up": question.get("follow_up") or "",
            }
            for question in (item.get("questions") or [])
        ]
        name = item.get("candidate_name") or f"候选人{item.get('candidate_id')}"
        messages.append(
            PlannedMessage(
                text=f"「{name}」的面试题（{len(questions)} 道）：",
                card_type=CARD_INTERVIEW,
                card_data={
                    "candidate_id": item.get("candidate_id"),
                    "name": name,
                    "count": len(questions),
                    "questions": questions,
                    "chips": [
                        {"label": f"➡️ 把{name}推到面试", "text": f"把{name}推到面试"}
                    ],
                },
                trace_id=data.get("trace_id"),
                cost=cost,
            )
        )
    return Execution(
        intent=intent,
        intent_label="生成面试题",
        messages=messages,
        trace_id=data.get("trace_id"),
        degraded=bool(data.get("degraded")),
        duration_ms=duration_ms,
        total_cost=cost,
    )


async def _run_resume_upload(
    db: AsyncSession, decision: nlu.Decision, payload: ChatSendIn, user
) -> Execution:
    wants_retry = bool(re.search(r"重试|重新解析|失败", payload.text))
    if not payload.file_ids and not wants_retry:
        # 只是表达「我要传简历」：先给上传卡，不顺手解析无关的历史文件
        return Execution(
            intent="resume_upload",
            intent_label="解析简历",
            messages=[
                PlannedMessage(
                    text="把文件拖进上传卡吧（支持 PDF / DOCX，可批量）。",
                    card_type=CARD_UPLOAD,
                    card_data={
                        "target_job_id": decision.slots.get("job_id"),
                        "target": decision.slots.get("job_title") or "未选择职位",
                    },
                )
            ],
        )

    data = await run_orchestration(
        db,
        _orch_payload(
            "resume_upload",
            file_ids=list(payload.file_ids),
            use_llm=payload.use_llm,
        ),
        user.id,
    )
    result = data.get("result") or {}
    total = int(result.get("total") or 0)
    success = int(result.get("success") or 0)
    failed = int(result.get("failed") or 0)

    if total == 0:
        return Execution(
            intent="resume_upload",
            intent_label="解析简历",
            messages=[
                PlannedMessage(
                    text="把文件拖进上传卡吧（支持 PDF / DOCX，可批量）。",
                    card_type=CARD_UPLOAD,
                    card_data={
                        "target_job_id": decision.slots.get("job_id"),
                        "target": decision.slots.get("job_title") or "未选择职位",
                    },
                )
            ],
            trace_id=data.get("trace_id"),
        )

    rows = []
    for item in result.get("items") or []:
        file_id = item.get("file_id")
        candidate_id = item.get("candidate_id")
        candidate = await db.get(Candidate, candidate_id) if candidate_id else None
        ok = item.get("status") == "success"
        rows.append(
            {
                "name": (candidate.name if candidate else None)
                or f"文件#{file_id}",
                "years": (
                    f"{float(candidate.years_experience):g} 年"
                    if candidate and candidate.years_experience is not None
                    else "—"
                ),
                "skills": list(candidate.skills or [])[:6] if candidate else [],
                "status": "ok" if ok else "fail",
                "error": item.get("error"),
            }
        )

    text = f"解析完成：{success} 份成功，{failed} 份失败。"
    chips = [{"label": "🎯 看看谁适合后端岗", "text": "看看这批简历谁适合后端岗"}]
    if failed:
        chips.append({"label": "🔁 重试失败的那份", "text": "重试解析失败的简历"})
    return Execution(
        intent="resume_upload",
        intent_label="解析简历",
        messages=[
            PlannedMessage(
                text=text,
                card_type=CARD_PARSE_RESULT,
                card_data={
                    "title": "解析结果",
                    "success": success,
                    "failed": failed,
                    "rows": rows,
                    "chips": chips,
                },
                trace_id=data.get("trace_id"),
                tokens=int(data.get("total_tokens") or 0),
                cost=float(data.get("total_cost") or 0),
            )
        ],
        trace_id=data.get("trace_id"),
        degraded=bool(data.get("degraded")),
        duration_ms=int(data.get("duration_ms") or 0),
        total_cost=float(data.get("total_cost") or 0),
    )


async def _run_jd(
    db: AsyncSession, decision: nlu.Decision, payload: ChatSendIn, user
) -> Execution:
    slots = decision.slots
    data = await run_orchestration(
        db,
        _orch_payload(
            "jd_generate",
            title=slots.get("title"),
            job_id=slots.get("job_id"),
            keywords=list(slots.get("skills") or []),
            use_llm=payload.use_llm,
        ),
        user.id,
    )
    result = data.get("result") or {}
    title = slots.get("title") or slots.get("job_title") or "职位"
    text = (
        f"「{title}」JD 草稿：\n\n"
        f"一句话介绍\n{result.get('summary') or '（暂无）'}\n\n"
        f"职位描述\n{result.get('description') or '（暂无）'}\n\n"
        f"任职要求\n{result.get('requirements') or '（暂无）'}"
    )
    skills = result.get("skills") or []
    if skills:
        text += "\n\n技能：" + "、".join(skills[:10])
    if not result.get("ai_generated"):
        text += "\n\n（LLM 不可用，已使用模板草稿，可直接在职位页编辑）"
    return Execution(
        intent="jd_generate",
        intent_label="生成 JD",
        messages=[
            PlannedMessage(
                text=text,
                trace_id=data.get("trace_id"),
                tokens=int(data.get("total_tokens") or 0),
                cost=float(data.get("total_cost") or 0),
            )
        ],
        trace_id=data.get("trace_id"),
        degraded=bool(data.get("degraded")),
        duration_ms=int(data.get("duration_ms") or 0),
        total_cost=float(data.get("total_cost") or 0),
    )


async def _run_analytics(
    db: AsyncSession, execution: Execution, payload: ChatSendIn, user
) -> Execution:
    # 走 Supervisor 的 AnalyticsAgent，保证看板问答也留下编排轨迹与成本归属
    trace = await run_orchestration(
        db,
        _orch_payload("analytics", use_llm=payload.use_llm),
        user.id,
    )
    result = trace.get("result") or {}
    overview = result.get("overview") or {}
    insights = list(result.get("insights") or [])

    # 渠道明细由确定性统计服务补齐（Supervisor 结果里只有洞察与概览）
    dashboard = await analytics_svc.dashboard(db)
    channels = dashboard.get("channels") or []
    total = max([int(row.get("total") or 0) for row in channels] + [1])
    chart_rows = [
        {
            "label": row.get("source") or "未知",
            "value": int(row.get("total") or 0),
            "conversion": float(row.get("conversion") or 0),
            "pct": round(int(row.get("total") or 0) / total * 100),
        }
        for row in channels[:6]
    ]
    if not insights:
        insights = [
            f"当前在招职位 {overview.get('open_jobs', 0)} 个，"
            f"累计投递 {overview.get('total_applications', 0)} 份",
            f"待面试 {overview.get('pending_interview', 0)} 人，"
            f"已入职 {overview.get('hired', 0)} 人",
        ]
    text = "本月招聘数据：\n" + "\n".join(f"· {line}" for line in insights)
    execution.messages = [
        PlannedMessage(
            text=text,
            card_type=CARD_CHART,
            card_data={
                "title": "渠道效果",
                "channels": chart_rows,
                "insights": insights,
                "chips": [
                    {"label": "🎯 看看谁适合后端岗", "text": "看看这批简历谁适合后端岗"}
                ],
            },
            trace_id=trace.get("trace_id"),
            tokens=int(trace.get("total_tokens") or 0),
            cost=float(trace.get("total_cost") or 0),
        )
    ]
    execution.trace_id = trace.get("trace_id")
    execution.degraded = bool(trace.get("degraded"))
    execution.duration_ms = int(trace.get("duration_ms") or 0)
    execution.total_cost = float(trace.get("total_cost") or 0)
    return execution


async def _run_search(db: AsyncSession, decision: nlu.Decision) -> Execution:
    slots = decision.slots
    rows, _ = await candidates_svc.list_candidates(db, limit=50)
    skills = [value.lower() for value in (slots.get("skills") or [])]
    min_years = slots.get("min_years")
    matched = []
    for row in rows:
        row_skills = [value.lower() for value in (row.skills or [])]
        if skills and not all(any(skill in item for item in row_skills) for skill in skills):
            continue
        if min_years is not None and (row.years_experience or 0) < min_years:
            continue
        matched.append(row)
    matched = matched[:10]

    if matched:
        lines = [
            f"· {row.name or '未命名'} · "
            f"{row.years_experience if row.years_experience is not None else '—'} 年 · "
            f"{'、'.join((row.skills or [])[:5]) or '技能未填'}"
            for row in matched
        ]
        text = f"人才库检索到 {len(matched)} 人：\n" + "\n".join(lines)
    else:
        text = "没有找到符合条件的候选人，可以放宽技能或年限再试。"
    return Execution(
        intent="search_candidates",
        intent_label="人才库检索",
        messages=[
            PlannedMessage(
                text=text,
                card_data={
                    "chips": [
                        {"label": "🎯 用当前职位匹配", "text": "看看这批人谁适合当前职位"}
                    ]
                },
            )
        ],
    )


async def _run_application_status(db: AsyncSession, decision: nlu.Decision) -> Execution:
    slots = decision.slots
    application = await pipeline.get_application_or_404(db, slots["application_id"])
    detail = await pipeline.build_detail(db, application)
    text = (
        f"{detail.candidate_name or '该候选人'}（{detail.job_title or '职位'}）：\n"
        f"· 当前状态：{detail.status_label}\n"
        f"· 匹配分：{detail.match_score if detail.match_score is not None else '—'}\n"
        f"· 已停留：{detail.days_in_stage} 天\n"
        f"· 可推进到：{'、'.join(APP_STATUS_LABELS.get(s, s) for s in detail.allowed_next) or '无'}"
    )
    return Execution(
        intent="application_status",
        intent_label="查候选人进度",
        messages=[
            PlannedMessage(
                text=text,
                card_data={
                    "chips": [
                        {
                            "label": f"➡️ 把{detail.candidate_name or '该候选人'}推到面试",
                            "text": f"把{detail.candidate_name or '该候选人'}推到面试",
                        }
                    ]
                },
            )
        ],
    )


# ---------------------------------------------------------------- 安全闸：确认卡
async def _build_confirm(
    db: AsyncSession, session: ChatSession, decision: nlu.Decision, user
) -> list[PlannedMessage]:
    slots = decision.slots
    intent = decision.intent

    if intent == "publish_job":
        job = await db.get(Job, slots["job_id"])
        if job is None:
            return [PlannedMessage(text="职位不存在，请到职位页确认。")]
        can_publish = user.role in (ROLE_MANAGER, ROLE_ADMIN)
        action = "publish_job" if can_publish else "submit_job"
        plan = (
            ["校验 JD 完整性（描述 / 要求 / 技能）", "发布职位并记录发布人"]
            if can_publish
            else ["校验 JD 完整性（描述 / 要求 / 技能）", "提交给用人经理审批"]
        )
        return [
            PlannedMessage(
                text=f"发布职位是一个写操作，先确认执行计划：",
                card_type=CARD_CONFIRM,
                card_data={
                    "action": action,
                    "status": "pending",
                    "job_id": job.id,
                    "job_title": job.title,
                    "plan": plan,
                    "warning": (
                        "发布后职位会出现在招聘中列表。"
                        if can_publish
                        else "当前角色不能直接发布，确认后将提交审批。"
                    ),
                },
            )
        ]

    application = await pipeline.get_application_or_404(db, slots["application_id"])
    detail = await pipeline.build_detail(db, application)
    target = (
        APP_REJECTED if intent == "reject_candidate" else slots.get("to_status")
    )
    target_label = APP_STATUS_LABELS.get(target, STATUS_TEXT.get(target or "", target or ""))
    warning = (
        "淘汰是不可逆操作，需要填写原因，并会记录审计日志。"
        if target == APP_REJECTED
        else "该操作会改变候选人状态并触发通知，请确认无误。"
    )
    allowed = sorted(APP_TRANSITIONS.get(application.status, set()))
    if target not in allowed:
        allowed_text = "、".join(APP_STATUS_LABELS.get(s, s) for s in allowed) or "无"
        warning = (
            f"当前状态「{APP_STATUS_LABELS.get(application.status, application.status)}」"
            f"不能直接转为「{target_label}」；允许：{allowed_text}。"
        )
    return [
        PlannedMessage(
            text="这个操作会改变候选人状态，先跟你确认：",
            card_type=CARD_CONFIRM,
            card_data={
                "action": "advance_status",
                "status": "pending",
                "application_id": application.id,
                "candidate_id": application.candidate_id,
                "candidate_name": detail.candidate_name,
                "job_id": application.job_id,
                "job_title": detail.job_title,
                "from_status": application.status,
                "from_label": APP_STATUS_LABELS.get(application.status, application.status),
                "to_status": target,
                "to_label": target_label,
                "requires_reason": target == APP_REJECTED,
                "warning": warning,
            },
        )
    ]


async def confirm_action(
    db: AsyncSession,
    session: ChatSession,
    message_id: int,
    user,
    *,
    note: str | None = None,
    offer_salary: int | None = None,
) -> dict:
    row = await db.get(ChatMessage, message_id)
    if row is None or row.session_id != session.id or row.role != ROLE_ASSISTANT:
        raise HTTPException(status_code=404, detail="待确认卡片不存在")
    data = dict(row.card_data or {})
    if row.card_type != CARD_CONFIRM or data.get("status") != "pending":
        raise HTTPException(status_code=400, detail="该操作已处理或无需确认")

    action = data.get("action")
    if action not in CONFIRM_ACTIONS:
        raise HTTPException(status_code=400, detail="未知的确认操作")

    note = (note or "").strip() or None
    trace_id: str | None = None
    degraded = False
    text = ""

    try:
        if action == "advance_status":
            target = data.get("to_status")
            if target == APP_REJECTED and not note:
                raise HTTPException(status_code=400, detail="淘汰候选人必须填写原因")
            result = await run_orchestration(
                db,
                _orch_payload(
                    "advance_status",
                    application_id=data.get("application_id"),
                    to_status=target,
                    note=note,
                    offer_salary=offer_salary,
                ),
                user.id,
            )
            trace_id = result.get("trace_id")
            degraded = bool(result.get("degraded"))
            outcome = result.get("result") or {}
            if outcome.get("allowed"):
                text = (
                    f"✓ 已更新：{data.get('candidate_name')} "
                    f"{data.get('from_label')} → {outcome.get('to_label')}。"
                    "流转历史已记录，相关通知已发送。"
                )
            else:
                text = f"未执行：{outcome.get('reason') or '状态机校验未通过'}"

        elif action == "publish_job":
            if user.role not in (ROLE_MANAGER, ROLE_ADMIN):
                raise HTTPException(
                    status_code=403, detail="招聘专员不能直接发布职位，请提交审批"
                )
            job = await job_svc.get_job_or_404(db, data.get("job_id"))
            await job_svc.publish_job(db, job, user.id)
            text = f"✓ 已发布职位「{job.title}」。"

        elif action == "submit_job":
            job = await job_svc.get_job_or_404(db, data.get("job_id"))
            await job_svc.submit_for_approval(db, job)
            text = f"✓ 已提交审批：「{job.title}」，等待用人经理审批。"

        data["status"] = "done"
        data["result_text"] = text
        row.card_data = data

        reply = _add_message(
            db,
            session,
            ROLE_ASSISTANT,
            content=text,
            intent=row.intent,
            trace_id=trace_id,
        )
        await db.commit()
        await db.refresh(row)
        await db.refresh(reply)
        await db.refresh(session)
        return {
            "message": message_out(reply),
            "trace_id": trace_id,
            "degraded": degraded,
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"确认操作失败 action={action}：{exc}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="执行失败，请稍后重试") from exc
