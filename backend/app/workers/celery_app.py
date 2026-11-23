"""
Celery 应用

启动（Windows 必须用 solo 池）：
    python -m celery -A app.workers.celery_app:celery_app worker --loglevel=info --pool=solo

不返回任务结果（task_ignore_result），后端只用任务的副作用：
解析完成后更新 resume_file 状态、索引完成后写 rag_chunk。
"""
from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "talentmatch",
    broker=settings.REDIS_URL,
    backend=None,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_ignore_result=True,
    task_track_started=True,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=max(settings.CELERY_TASK_TIME_LIMIT - 30, 30),
    broker_connection_retry_on_startup=True,
    # 任务失败后不无限重投；解析/索引失败由业务层落状态，避免重复副作用
    task_acks_late=False,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
)
