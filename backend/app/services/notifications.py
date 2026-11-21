"""
站内通知服务（阶段六）

状态流转成功即算业务成功；通知只做记录，不阻断流程。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import (
    APP_HIRED,
    APP_INTERVIEW,
    APP_OFFER,
    APP_REJECTED,
    APP_SCREENING,
    Application,
)
from app.models.base import utcnow
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import (
    NOTIF_CHANNEL_INAPP,
    NOTIF_READ,
    NOTIF_SENT,
    Notification,
)

# to_status -> (template, subject, body 模板)
STATUS_TEMPLATES: dict[str, tuple[str, str, str]] = {
    APP_SCREENING: (
        "status_update",
        "候选人进入筛选阶段",
        "候选人 {name} 应聘「{job}」已进入筛选阶段，请安排简历评估。",
    ),
    APP_INTERVIEW: (
        "interview_invite",
        "候选人进入面试阶段",
        "候选人 {name} 应聘「{job}」已进入面试阶段，请准备面试评估。",
    ),
    APP_OFFER: (
        "offer",
        "候选人待发 Offer",
        "候选人 {name} 应聘「{job}」已进入 Offer 阶段，请确认薪资方案。",
    ),
    APP_HIRED: (
        "status_update",
        "候选人已入职",
        "候选人 {name} 已入职「{job}」，流程完成。",
    ),
    APP_REJECTED: (
        "rejected",
        "候选人已淘汰",
        "候选人 {name} 应聘「{job}」已被淘汰{reason}。",
    ),
}


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int | None,
    application_id: int | None,
    candidate_id: int | None,
    template: str,
    subject: str,
    body: str,
    channel: str = NOTIF_CHANNEL_INAPP,
    to_addr: str | None = None,
) -> Notification:
    """写入一条已发送的站内通知（开发期不接真实邮件通道）"""
    notification = Notification(
        user_id=user_id,
        application_id=application_id,
        candidate_id=candidate_id,
        channel=channel,
        template=template,
        subject=subject,
        body=body,
        to_addr=to_addr,
        status=NOTIF_SENT,
        sent_at=utcnow(),
        company_id=1,
    )
    db.add(notification)
    await db.flush()
    return notification


async def notify_status_change(
    db: AsyncSession,
    *,
    application: Application,
    from_status: str,
    to_status: str,
    note: str | None,
    operator_id: int | None,
) -> Notification | None:
    """按目标状态生成通知，接收人优先职位创建人"""
    template_info = STATUS_TEMPLATES.get(to_status)
    if template_info is None:
        return None

    job = await db.get(Job, application.job_id)
    candidate = await db.get(Candidate, application.candidate_id)
    name = (candidate.name if candidate else None) or f"候选人#{application.candidate_id}"
    job_title = (job.title if job else None) or f"职位#{application.job_id}"

    template, subject, body_template = template_info
    reason = f"，原因：{note}" if to_status == APP_REJECTED and note else ""
    body = body_template.format(name=name, job=job_title, reason=reason)

    recipient = (
        (job.created_by if job else None)
        or application.created_by
        or operator_id
    )
    return await create_notification(
        db,
        user_id=recipient,
        application_id=application.id,
        candidate_id=application.candidate_id,
        template=template,
        subject=subject,
        body=body,
    )


async def list_notifications(
    db: AsyncSession,
    user_id: int,
    *,
    unread_only: bool = False,
    limit: int = 50,
) -> tuple[list[Notification], int]:
    """当前用户的站内通知 + 未读数"""
    conditions = [Notification.user_id == user_id]
    if unread_only:
        conditions.append(Notification.status != NOTIF_READ)

    rows = (
        await db.execute(
            select(Notification)
            .where(*conditions)
            .order_by(Notification.create_time.desc(), Notification.id.desc())
            .limit(limit)
        )
    ).scalars().all()

    unread = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.status != NOTIF_READ)
        )
    ).scalar_one()
    return list(rows), int(unread)


async def unread_count(db: AsyncSession, user_id: int) -> int:
    count = (
        await db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.status != NOTIF_READ)
        )
    ).scalar_one()
    return int(count)


async def mark_read(
    db: AsyncSession, notification_id: int, user_id: int
) -> Notification | None:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.user_id != user_id:
        return None
    if notification.status != NOTIF_READ:
        notification.status = NOTIF_READ
        notification.read_at = utcnow()
        await db.commit()
        await db.refresh(notification)
    return notification
