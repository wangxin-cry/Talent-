"""
Celery 任务入口

- 业务函数都是 async，这里用进程内常驻事件循环跑，
  避免每个任务新建 loop 导致 asyncpg 连接绑到已关闭的 loop 上；
- 任务只做副作用，不返回结果；失败由业务层写入状态与通知。
"""
from __future__ import annotations

import asyncio

from app.core.logging import logger
from app.services import candidates, rag
from app.workers.celery_app import celery_app

_loop: asyncio.AbstractEventLoop | None = None


def _run(coro):
    """在 worker 进程内复用同一个事件循环"""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


@celery_app.task(name="talentmatch.parse_resume")
def parse_resume_task(file_id: int, trace_id: str | None = None) -> None:
    logger.info(f"[celery] 开始解析简历 file_id={file_id} trace={trace_id}")
    _run(candidates.run_parse_task(file_id, trace_id))
    logger.info(f"[celery] 简历解析任务结束 file_id={file_id}")


@celery_app.task(name="talentmatch.index_resume")
def index_resume_task(candidate_id: int) -> None:
    _run(rag.index_resume_task(candidate_id))


@celery_app.task(name="talentmatch.index_job")
def index_job_task(job_id: int) -> None:
    _run(rag.index_job_task(job_id))


@celery_app.task(name="talentmatch.index_questions")
def index_questions_task(application_id: int) -> None:
    _run(rag.index_questions_task(application_id))
