"""
面试安排与评估（PRD RA-02 / IA-02 / IA-03）

- 面试安排：时间 / 时长 / 形式 / 地点 / 面试官，可导出 .ics 日历文件
- 评估模板：固定六维度 1~5 分 + 结论
- 评估记录：按投递聚合，给出平均分与综合结论
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decrypt_pii
from app.models.base import utcnow
from app.models.application import Application
from app.models.candidate import Candidate
from app.models.interview import (
    RECOMMENDATION_LABELS,
    InterviewFeedback,
    InterviewSchedule,
)
from app.models.job import Job
from app.models.notification import (
    NOTIF_CHANNEL_EMAIL,
    NOTIF_FAILED,
    NOTIF_SENT,
    Notification,
)
from app.services import email as email_svc
from app.services import notifications as notification_svc

MODE_LABELS = {"online": "线上", "onsite": "现场", "phone": "电话"}
CST = timezone(timedelta(hours=8))

EVALUATION_DIMENSIONS = [
    {"key": "professional", "name": "专业技能", "description": "岗位核心技能掌握程度与实战深度"},
    {"key": "problem_solving", "name": "解决问题", "description": "分析问题、拆解思路与落地能力"},
    {"key": "communication", "name": "沟通表达", "description": "表达清晰度、倾听与反馈质量"},
    {"key": "teamwork", "name": "团队协作", "description": "协作意识、冲突处理与推动力"},
    {"key": "learning", "name": "学习潜力", "description": "学习速度、复盘意识与成长空间"},
    {"key": "culture_fit", "name": "文化匹配", "description": "价值观与团队氛围的契合度"},
]

EVALUATION_TEMPLATE = {
    "title": "结构化面试评估表",
    "scale": 5,
    "dimensions": EVALUATION_DIMENSIONS,
    "recommendations": [
        {"value": key, "label": label} for key, label in RECOMMENDATION_LABELS.items()
    ],
}


async def get_schedule(db: AsyncSession, application_id: int) -> InterviewSchedule | None:
    return (
        await db.execute(
            select(InterviewSchedule).where(InterviewSchedule.application_id == application_id)
        )
    ).scalar_one_or_none()


async def _application_context(
    db: AsyncSession, application_id: int
) -> tuple[Application | None, Job | None, Candidate | None]:
    application = await db.get(Application, application_id)
    if application is None:
        return None, None, None
    job = await db.get(Job, application.job_id)
    candidate = await db.get(Candidate, application.candidate_id)
    return application, job, candidate


async def _notify_related_users(
    db: AsyncSession,
    application_id: int,
    *,
    operator_id: int | None,
    template: str,
    subject: str,
    body: str,
) -> None:
    """通知投递创建人和职位创建人（排除操作人自己）"""
    application, job, _ = await _application_context(db, application_id)
    if application is None:
        return

    recipients = {application.created_by, job.created_by if job else None}
    for user_id in recipients:
        if not user_id or user_id == operator_id:
            continue
        await notification_svc.create_notification(
            db,
            user_id=user_id,
            application_id=application_id,
            candidate_id=application.candidate_id,
            template=template,
            subject=subject,
            body=body,
        )
    await db.commit()


async def _send_candidate_invite(
    db: AsyncSession,
    *,
    application: Application,
    job: Job | None,
    candidate: Candidate,
    schedule: InterviewSchedule,
    email_addr: str,
) -> None:
    """给候选人发面试邀请邮件（未配置 SMTP 时只记录失败，不阻断流程）"""
    name = candidate.name or "同学"
    title = job.title if job else f"职位#{application.job_id}"
    mode = MODE_LABELS.get(schedule.mode, schedule.mode or "待定")
    place = schedule.location or ("线上会议" if schedule.mode == "online" else "待定")

    local_time: datetime = schedule.scheduled_at
    if local_time.tzinfo is None:
        local_time = local_time.replace(tzinfo=timezone.utc)
    local_time = local_time.astimezone(CST)

    body = (
        f"{name}，你好：\n\n"
        f"你应聘的「{title}」已安排面试。\n"
        f"时间：{local_time:%Y-%m-%d %H:%M}\n"
        f"形式：{mode}\n"
        f"地点：{place}\n"
        f"面试官：{schedule.interviewer or '待定'}\n"
    )
    if schedule.note:
        body += f"备注：{schedule.note}\n"
    body += "\n请提前 10 分钟做好准备；如时间冲突，请回复本邮件说明。"

    sent = await email_svc.send_mail(email_addr, "【TalentMatch】面试邀请", body)
    db.add(
        Notification(
            user_id=None,
            application_id=application.id,
            candidate_id=candidate.id,
            channel=NOTIF_CHANNEL_EMAIL,
            template="interview_invite",
            subject="面试邀请",
            body=body,
            to_addr=email_addr,
            status=NOTIF_SENT if sent else NOTIF_FAILED,
            sent_at=utcnow() if sent else None,
            company_id=application.company_id,
        )
    )
    await db.commit()


async def upsert_schedule(db: AsyncSession, application_id: int, data, user_id: int) -> InterviewSchedule:
    schedule = await get_schedule(db, application_id)
    if schedule is None:
        schedule = InterviewSchedule(application_id=application_id, created_by=user_id)
        db.add(schedule)
    schedule.scheduled_at = data.scheduled_at
    schedule.duration_minutes = data.duration_minutes
    schedule.mode = data.mode
    schedule.location = data.location
    schedule.interviewer = data.interviewer
    schedule.note = data.note
    await db.commit()
    await db.refresh(schedule)

    application, job, candidate = await _application_context(db, application_id)
    if application is not None:
        name = (candidate.name if candidate else None) or f"候选人#{application.candidate_id}"
        title = (job.title if job else None) or f"职位#{application.job_id}"
        await _notify_related_users(
            db,
            application_id,
            operator_id=user_id,
            template="interview_scheduled",
            subject="面试已安排",
            body=(
                f"候选人 {name} 应聘「{title}」的面试已安排在 "
                f"{schedule.scheduled_at:%Y-%m-%d %H:%M}。"
            ),
        )

        email_addr = decrypt_pii(candidate.email_enc) if candidate and candidate.email_enc else None
        if email_addr:
            await _send_candidate_invite(
                db,
                application=application,
                job=job,
                candidate=candidate,
                schedule=schedule,
                email_addr=email_addr,
            )
    return schedule


def _ics_escape(value: str | None) -> str:
    text = (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return text.replace("\r\n", "\\n").replace("\n", "\\n")


def build_ics(
    schedule: InterviewSchedule,
    *,
    job_title: str,
    candidate_name: str,
    application_id: int,
) -> str:
    """按 RFC 5545 生成日历事件；时间按 UTC 输出"""
    start = schedule.scheduled_at
    end = start + timedelta(minutes=schedule.duration_minutes or 60)
    stamp = utcnow()
    mode_label = {"online": "线上", "onsite": "现场", "phone": "电话"}.get(schedule.mode, schedule.mode)
    description = f"面试形式：{mode_label}\n候选人：{candidate_name}\n职位：{job_title}"
    if schedule.note:
        description += f"\n备注：{schedule.note}"

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//TalentMatch//Interview Schedule//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:interview-{application_id}-{int(start.timestamp())}@talentmatch",
        f"DTSTAMP:{stamp:%Y%m%dT%H%M%SZ}",
        f"DTSTART:{start:%Y%m%dT%H%M%SZ}",
        f"DTEND:{end:%Y%m%dT%H%M%SZ}",
        f"SUMMARY:{_ics_escape(f'面试：{candidate_name} · {job_title}')}",
        f"LOCATION:{_ics_escape(schedule.location or ('线上会议' if schedule.mode == 'online' else ''))}",
        f"DESCRIPTION:{_ics_escape(description)}",
        "STATUS:CONFIRMED",
        "BEGIN:VALARM",
        "TRIGGER:-PT30M",
        "ACTION:DISPLAY",
        "DESCRIPTION:面试提醒",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lines) + "\r\n"


def _feedback_out(item: InterviewFeedback) -> dict:
    return {
        "id": item.id,
        "application_id": item.application_id,
        "interviewer_id": item.interviewer_id,
        "interviewer_name": item.interviewer_name,
        "round": item.round,
        "scores": item.scores or {},
        "overall_rating": item.overall_rating,
        "recommendation": item.recommendation,
        "recommendation_label": RECOMMENDATION_LABELS.get(item.recommendation or ""),
        "comment": item.comment,
        "create_time": item.create_time,
    }


async def create_feedback(
    db: AsyncSession, application_id: int, data, user
) -> InterviewFeedback:
    scores = {
        str(key): int(value) for key, value in (data.scores or {}).items() if 1 <= int(value) <= 5
    }
    overall = data.overall_rating
    if overall is None and scores:
        overall = round(sum(scores.values()) / len(scores), 2)
    feedback = InterviewFeedback(
        application_id=application_id,
        interviewer_id=getattr(user, "id", None),
        interviewer_name=getattr(user, "name", None),
        round=data.round,
        scores=scores,
        overall_rating=overall,
        recommendation=data.recommendation,
        comment=data.comment,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    application, job, candidate = await _application_context(db, application_id)
    if application is not None:
        name = (candidate.name if candidate else None) or f"候选人#{application.candidate_id}"
        title = (job.title if job else None) or f"职位#{application.job_id}"
        label = RECOMMENDATION_LABELS.get(feedback.recommendation, "未给结论")
        score = feedback.overall_rating if feedback.overall_rating is not None else "-"
        await _notify_related_users(
            db,
            application_id,
            operator_id=getattr(user, "id", None),
            template="interview_feedback",
            subject="面试评估已提交",
            body=f"候选人 {name}（{title}）第 {feedback.round} 轮面试评估已提交：{score} 分，{label}。",
        )
    return feedback


async def list_feedbacks(db: AsyncSession, application_id: int) -> list[InterviewFeedback]:
    return list(
        (
            await db.execute(
                select(InterviewFeedback)
                .where(InterviewFeedback.application_id == application_id)
                .order_by(InterviewFeedback.round.asc(), InterviewFeedback.id.asc())
            )
        ).scalars().all()
    )


def feedback_summary(items: list[InterviewFeedback]) -> dict:
    ratings = [item.overall_rating for item in items if item.overall_rating is not None]
    recommendations = [item.recommendation for item in items if item.recommendation]
    top = Counter(recommendations).most_common(1)[0][0] if recommendations else None
    return {
        "total": len(items),
        "average_rating": round(sum(ratings) / len(ratings), 2) if ratings else None,
        "recommendation": top,
        "recommendation_label": RECOMMENDATION_LABELS.get(top or ""),
        "items": [_feedback_out(item) for item in items],
    }
