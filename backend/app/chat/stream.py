"""对话事件流（SSE）任务注册表

用途：POST 只负责「发起任务」并立即返回 task_id；GET 用 SSE 订阅进度与最终结果。
- 事件带自增 id，支持断线后用 Last-Event-ID / after 重放；
- 任务只存在于当前进程（单实例演示够用），完成后保留 30 分钟便于重连；
- 真正的业务执行仍在 engine.handle_message，流式层只做事件转发。
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from loguru import logger
from pydantic import BaseModel

from app.core.database import SessionLocal
from app.models.chat import ChatSession
from app.models.user import User
from app.schemas.chat import ChatSendIn

TASK_TTL_SECONDS = 30 * 60
MAX_TASKS = 200


@dataclass
class ChatTask:
    id: str
    session_id: int
    user_id: int
    events: list[dict] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    done: bool = False
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    worker: asyncio.Task | None = None
    _seq: int = 0

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq


_TASKS: dict[str, ChatTask] = {}


def _prune() -> None:
    now = time.time()
    expired = [
        key
        for key, task in _TASKS.items()
        if task.done
        and task.finished_at is not None
        and now - task.finished_at > TASK_TTL_SECONDS
    ]
    for key in expired:
        _TASKS.pop(key, None)

    if len(_TASKS) <= MAX_TASKS:
        return
    # 超量时优先淘汰已完成的旧任务
    finished = sorted(
        (task for task in _TASKS.values() if task.done),
        key=lambda task: task.finished_at or 0,
    )
    for task in finished[: max(0, len(_TASKS) - MAX_TASKS)]:
        _TASKS.pop(task.id, None)


def get_task(task_id: str) -> ChatTask | None:
    return _TASKS.get(task_id)


async def publish(task: ChatTask, event: dict) -> None:
    """追加事件并唤醒所有订阅者"""
    payload = {**event, "id": task.next_seq()}
    task.events.append(payload)
    async with task.condition:
        task.condition.notify_all()


async def _finish(task: ChatTask) -> None:
    task.done = True
    task.finished_at = time.time()
    async with task.condition:
        task.condition.notify_all()


def _json_default(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def format_sse(event: dict) -> str:
    body = json.dumps(event, ensure_ascii=False, default=_json_default)
    return f"id: {event.get('id', 0)}\nevent: {event.get('type', 'message')}\ndata: {body}\n\n"


async def stream_events(task: ChatTask, after: int = 0):
    """按顺序重放缓冲事件，再等待新事件；收到 done/error 后结束"""
    index = max(0, after)
    while True:
        if index < len(task.events):
            event = task.events[index]
            index += 1
            yield format_sse(event)
            if event.get("type") in ("done", "error"):
                return
            continue

        if task.done:
            return

        timed_out = False
        async with task.condition:
            if index >= len(task.events) and not task.done:
                try:
                    await asyncio.wait_for(task.condition.wait(), timeout=15)
                except asyncio.TimeoutError:
                    timed_out = True
        if timed_out:
            yield ": ping\n\n"


async def _run_task(task: ChatTask, payload: ChatSendIn) -> None:
    """后台执行一轮对话，把进度与结果写进事件流"""
    try:
        from app.chat.engine import get_session_or_404, handle_message

        async with SessionLocal() as db:
            session = await get_session_or_404(db, task.session_id, task.user_id)
            user = await db.get(User, task.user_id)
            if user is None:
                raise RuntimeError("用户不存在")
            result = await handle_message(
                db,
                session,
                payload,
                user,
                emit=lambda event: publish(task, event),
            )
        await publish(task, {"type": "done", **result})
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"对话流式任务失败 task={task.id}：{exc}")
        await publish(
            task,
            {
                "type": "error",
                "message": "执行失败，请稍后重试；页面上的同名按钮仍然可用。",
            },
        )
    finally:
        await _finish(task)


def start_task(
    session_id: int, user_id: int, payload: ChatSendIn
) -> ChatTask:
    """创建任务并立即在后台执行（调用方必须处于事件循环中）"""
    _prune()
    task = ChatTask(
        id=uuid.uuid4().hex,
        session_id=session_id,
        user_id=user_id,
    )
    _TASKS[task.id] = task
    task.worker = asyncio.create_task(_run_task(task, payload))
    return task
