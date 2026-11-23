"""
后台任务分发

QUEUE_MODE=memory（默认）：沿用 FastAPI BackgroundTasks，进程内执行；
QUEUE_MODE=celery：投递到 Redis，由独立 worker 消费。

API 层只调这里，不直接依赖 BackgroundTasks / Celery，
以后换队列（ARQ、RQ）也只需要改本文件。
"""
from __future__ import annotations

from fastapi import BackgroundTasks

from app.core.config import settings
from app.services import candidates, rag


def enqueue_parse_resume(
    background: BackgroundTasks, file_id: int, trace_id: str | None = None
) -> None:
    """简历解析（耗时最长，推荐走 Celery）"""
    if settings.celery_enabled:
        from app.workers.tasks import parse_resume_task

        parse_resume_task.delay(file_id, trace_id)
        return
    background.add_task(candidates.run_parse_task, file_id, trace_id)


def enqueue_index_resume(background: BackgroundTasks, candidate_id: int) -> None:
    if settings.celery_enabled:
        from app.workers.tasks import index_resume_task

        index_resume_task.delay(candidate_id)
        return
    background.add_task(rag.index_resume_task, candidate_id)


def enqueue_index_job(background: BackgroundTasks, job_id: int) -> None:
    if settings.celery_enabled:
        from app.workers.tasks import index_job_task

        index_job_task.delay(job_id)
        return
    background.add_task(rag.index_job_task, job_id)


def enqueue_index_questions(background: BackgroundTasks, application_id: int) -> None:
    if settings.celery_enabled:
        from app.workers.tasks import index_questions_task

        index_questions_task.delay(application_id)
        return
    background.add_task(rag.index_questions_task, application_id)
