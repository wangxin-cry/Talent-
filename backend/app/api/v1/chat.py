"""对话式入口接口（阶段九½）

前缀：/api/v1/chat
- 工具注册表
- 会话列表 / 新建 / 详情 / 上下文更新
- 发消息（意图识别 + 安全闸 + 编排 + 卡片）
- 确认不可逆操作
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.chat import (
    INTENT_META,
    confirm_action,
    get_session_or_404,
    handle_message,
    session_payload,
    session_payloads,
    tool_table,
)
from app.chat.engine import message_out
from app.chat.stream import get_task, start_task, stream_events
from app.core.deps import CurrentUser, DbSession
from app.models.chat import ChatMessage, ChatSession
from app.schemas.chat import (
    ChatConfirmIn,
    ChatConfirmOut,
    ChatIntentListOut,
    ChatSendIn,
    ChatSendOut,
    ChatSessionCreateIn,
    ChatSessionDetailOut,
    ChatSessionListOut,
    ChatSessionOut,
    ChatSessionUpdateIn,
    ChatStreamStartOut,
    ChatToolListOut,
)

router = APIRouter(prefix="/chat", tags=["对话式入口"])


# ---------------------------------------------------------------- 工具与意图
@router.get("/tools", response_model=ChatToolListOut, summary="对话工具注册表")
async def tools_api(_: CurrentUser) -> ChatToolListOut:
    return ChatToolListOut(items=tool_table())


@router.get("/intents", response_model=ChatIntentListOut, summary="对话意图 → 工具映射")
async def intents_api(_: CurrentUser) -> ChatIntentListOut:
    return ChatIntentListOut(
        items=[
            {
                "intent": key,
                "label": value["label"],
                "level": value["level"],
                "tool": value["tool"],
            }
            for key, value in INTENT_META.items()
        ]
    )


# ---------------------------------------------------------------- 会话
@router.get("/sessions", response_model=ChatSessionListOut, summary="会话列表")
async def list_sessions_api(
    db: DbSession,
    user: CurrentUser,
    include_empty: bool = Query(
        default=False, description="是否包含还没有任何消息的空会话"
    ),
) -> ChatSessionListOut:
    rows = (
        await db.execute(
            select(ChatSession)
            .where(ChatSession.user_id == user.id)
            .order_by(
                func.coalesce(
                    ChatSession.last_message_at, ChatSession.create_time
                ).desc(),
                ChatSession.id.desc(),
            )
            .limit(50)
        )
    ).scalars().all()

    items = await session_payloads(db, list(rows))
    if not include_empty:
        # 空会话（点过「新会话」但没说话）不进列表，避免侧栏堆积无意义的空会话
        items = [item for item in items if item.message_count > 0]
    return ChatSessionListOut(items=items, total=len(items))


@router.post(
    "/sessions",
    response_model=ChatSessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建会话",
)
async def create_session_api(
    payload: ChatSessionCreateIn, db: DbSession, user: CurrentUser
) -> ChatSessionOut:
    session = ChatSession(
        user_id=user.id,
        company_id=1,
        title=payload.title,
        context_job_id=payload.context_job_id,
        context_candidate_id=payload.context_candidate_id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return await session_payload(db, session)


@router.get(
    "/sessions/{session_id}",
    response_model=ChatSessionDetailOut,
    summary="会话详情（含历史消息）",
)
async def session_detail_api(
    session_id: int, db: DbSession, user: CurrentUser
) -> ChatSessionDetailOut:
    session = await get_session_or_404(db, session_id, user.id)
    rows = (
        await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .order_by(ChatMessage.id.asc())
        )
    ).scalars().all()
    return ChatSessionDetailOut(
        session=await session_payload(db, session),
        messages=[message_out(row) for row in rows],
    )


@router.patch(
    "/sessions/{session_id}",
    response_model=ChatSessionOut,
    summary="更新会话标题 / 当前上下文",
)
async def update_session_api(
    session_id: int,
    payload: ChatSessionUpdateIn,
    db: DbSession,
    user: CurrentUser,
) -> ChatSessionOut:
    session = await get_session_or_404(db, session_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(session, field, value)
    await db.commit()
    await db.refresh(session)
    return await session_payload(db, session)


# ---------------------------------------------------------------- 消息
@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatSendOut,
    summary="发消息（同步兜底，一次性返回完整结果）",
)
async def send_message_api(
    session_id: int,
    payload: ChatSendIn,
    db: DbSession,
    user: CurrentUser,
) -> ChatSendOut:
    session = await get_session_or_404(db, session_id, user.id)
    data = await handle_message(db, session, payload, user)
    return ChatSendOut(**data)


@router.post(
    "/sessions/{session_id}/messages/stream",
    response_model=ChatStreamStartOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="发起流式对话任务（随后用 GET 订阅 SSE）",
)
async def start_stream_api(
    session_id: int,
    payload: ChatSendIn,
    db: DbSession,
    user: CurrentUser,
) -> ChatStreamStartOut:
    session = await get_session_or_404(db, session_id, user.id)
    task = start_task(session.id, user.id, payload)
    return ChatStreamStartOut(task_id=task.id, session_id=session.id)


@router.get(
    "/sessions/{session_id}/tasks/{task_id}/events",
    summary="订阅对话任务 SSE（status / intent / done / error）",
)
async def stream_events_api(
    session_id: int,
    task_id: str,
    db: DbSession,
    user: CurrentUser,
    after: int = Query(default=0, ge=0, description="从该事件 id 之后重放"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    session = await get_session_or_404(db, session_id, user.id)
    task = get_task(task_id)
    if task is None or task.session_id != session.id or task.user_id != user.id:
        raise HTTPException(status_code=404, detail="对话任务不存在或已过期")

    cursor = after
    if last_event_id:
        try:
            cursor = max(cursor, int(last_event_id))
        except ValueError:
            cursor = after

    return StreamingResponse(
        stream_events(task, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/sessions/{session_id}/confirm",
    response_model=ChatConfirmOut,
    summary="确认不可逆 / 受控写操作",
)
async def confirm_api(
    session_id: int,
    payload: ChatConfirmIn,
    db: DbSession,
    user: CurrentUser,
) -> ChatConfirmOut:
    session = await get_session_or_404(db, session_id, user.id)
    data = await confirm_action(
        db,
        session,
        payload.message_id,
        user,
        note=payload.note,
        offer_salary=payload.offer_salary,
    )
    return ChatConfirmOut(**data)
