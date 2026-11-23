"""
站内通知服务（阶段六）

状态流转成功即算业务成功；通知只做记录，不阻断流程。
"""
from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.core.security import decrypt_pii
from app.core.tenant import require_company_id
from app.models.application import (
    APP_HIRED,
    APP_INTERVIEW,
    APP_NEW,
    APP_OFFER,
    APP_REJECTED,
    APP_SCREENING,
    Application,
)
from app.models.base import utcnow
from app.models.candidate import Candidate
from app.models.interview import ApplicationTracking
from app.models.job import Job
from app.models.notification import (
    NOTIF_CHANNEL_EMAIL,
    NOTIF_CHANNEL_INAPP,
    NOTIF_FAILED,
    NOTIF_READ,
    NOTIF_SENT,
    Notification,
)
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, STATUS_ACTIVE, User
from app.services import email as email_svc

REVIEWER_ROLES = {ROLE_MANAGER, ROLE_ADMIN}

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

# 发给候选人的邮件（CE-03：各节点自动反馈）
CANDIDATE_STATUS_TEMPLATES: dict[str, tuple[str, str, str]] = {
    APP_NEW: (
        "candidate_applied",
        "投递成功",
        "你好 {name}：\n\n我们已收到你投递的「{job}」，会尽快安排评估。",
    ),
    APP_SCREENING: (
        "candidate_screening",
        "简历评估中",
        "你好 {name}：\n\n你投递的「{job}」正在评估中，有进展会第一时间通知你。",
    ),
    APP_INTERVIEW: (
        "candidate_interview",
        "面试邀请",
        "你好 {name}：\n\n你投递的「{job}」已进入面试阶段，我们会尽快与你确认面试时间。{reason}",
    ),
    APP_OFFER: (
        "candidate_offer",
        "Offer 沟通",
        "你好 {name}：\n\n恭喜！你投递的「{job}」已进入 Offer 阶段，HR 将与你沟通具体方案。",
    ),
    APP_HIRED: (
        "candidate_hired",
        "欢迎加入",
        "你好 {name}：\n\n欢迎加入！期待与你一起共事。",
    ),
    APP_REJECTED: (
        "candidate_rejected",
        "流程结果通知",
        "你好 {name}：\n\n感谢你关注「{job}」，本次流程已结束{reason}。祝求职顺利。",
    ),
}


async def create_notification(
    db: AsyncSession,
    *,
    user_id: int | None,
    application_id: int | None = None,
    candidate_id: int | None = None,
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
        company_id=require_company_id(),
    )
    db.add(notification)
    await db.flush()
    return notification


async def notify_roles(
    db: AsyncSession,
    *,
    roles: set[str],
    template: str,
    subject: str,
    body: str,
    exclude_user_ids: set[int] | None = None,
    application_id: int | None = None,
    candidate_id: int | None = None,
) -> int:
    """按角色群发站内通知（排除操作人/已单独通知的人），返回写入条数"""
    exclude = exclude_user_ids or set()
    company_id = require_company_id()
    user_ids = (
        await db.execute(
            select(User.id).where(
                User.role.in_(list(roles)),
                User.status == STATUS_ACTIVE,
                User.company_id == company_id,
            )
        )
    ).scalars().all()

    sent = 0
    for user_id in user_ids:
        if user_id in exclude:
            continue
        await create_notification(
            db,
            user_id=user_id,
            application_id=application_id,
            candidate_id=candidate_id,
            template=template,
            subject=subject,
            body=body,
        )
        sent += 1
    return sent


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


async def notify_candidate_status(
    db: AsyncSession,
    *,
    application: Application,
    to_status: str,
    note: str | None = None,
) -> Notification | None:
    """给候选人发邮件（CE-03）；未配置 SMTP 时由邮件服务降级为日志，不阻断流程"""
    template_info = CANDIDATE_STATUS_TEMPLATES.get(to_status)
    if template_info is None:
        return None

    candidate = await db.get(Candidate, application.candidate_id)
    email_addr = decrypt_pii(candidate.email_enc) if candidate else None
    if not email_addr:
        return None

    job = await db.get(Job, application.job_id)
    name = (candidate.name if candidate else None) or "同学"
    job_title = (job.title if job else None) or f"职位#{application.job_id}"
    reason = f"，原因：{note}" if to_status == APP_REJECTED and note else ""
    template, subject, body_template = template_info
    body = body_template.format(name=name, job=job_title, reason=reason)

    tracking = (
        await db.execute(
            select(ApplicationTracking).where(
                ApplicationTracking.application_id == application.id,
                ApplicationTracking.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    link = (
        f"{base}/careers/status?token={quote(tracking.token)}&email={quote(email_addr)}"
        if tracking
        else f"{base}/careers"
    )

    sent = False
    try:
        sent = await email_svc.send_mail(email_addr, f"【TalentMatch】{subject}", f"{body}\n\n查看进度：{link}")
    except Exception as exc:  # pragma: no cover - 邮件通道异常不影响主流程
        logger.warning(f"候选人通知邮件发送失败：{exc}")

    notification = Notification(
        user_id=None,
        application_id=application.id,
        candidate_id=application.candidate_id,
        channel=NOTIF_CHANNEL_EMAIL,
        template=template,
        subject=subject,
        body=body,
        to_addr=email_addr,
        status=NOTIF_SENT if sent else NOTIF_FAILED,
        sent_at=utcnow() if sent else None,
        company_id=application.company_id,
    )
    db.add(notification)
    await db.commit()
    return notification


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
