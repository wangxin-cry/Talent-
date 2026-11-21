"""
招聘流程服务（阶段六）

职责：
- 创建应聘记录（同一职位同一候选人只允许一条）
- 状态机校验 + 流转历史 + 站内通知
- 看板分列、候选人详情、时间线

状态机是确定性代码，绝不由 LLM 判断。
"""
from __future__ import annotations

from fastapi import HTTPException, status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import (
    APP_HIRED,
    APP_NEW,
    APP_OFFER,
    APP_REJECTED,
    APP_STATUSES,
    APP_STATUS_LABELS,
    APP_TRANSITIONS,
    Application,
    ApplicationStageHistory,
)
from app.models.base import utcnow
from app.models.candidate import Candidate, Resume
from app.models.job import Job
from app.models.match_result import MatchResult
from app.models.user import User
from app.schemas.application import (
    ApplicationCardOut,
    ApplicationDetailOut,
    ApplicationTransitionIn,
    BoardColumnOut,
    BoardOut,
    HistoryOut,
    MatchGapOut,
    ResumeProjectOut,
    TimelineOut,
)
from app.services import notifications as notification_svc


def label(status_value: str) -> str:
    return APP_STATUS_LABELS.get(status_value, status_value)


def _days_in_stage(stage_entered_at) -> int:
    if stage_entered_at is None:
        return 0
    return max(0, int((utcnow() - stage_entered_at).total_seconds() // 86400))


async def get_application_or_404(db: AsyncSession, application_id: int) -> Application:
    application = await db.get(Application, application_id)
    if application is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="应聘记录不存在"
        )
    return application


async def _primary_resume(db: AsyncSession, candidate_id: int) -> Resume | None:
    row = (
        await db.execute(
            select(Resume)
            .where(Resume.candidate_id == candidate_id, Resume.is_primary.is_(True))
            .order_by(Resume.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return row


def _project_briefs(structured: dict | None) -> list[ResumeProjectOut]:
    briefs: list[ResumeProjectOut] = []
    for item in (structured or {}).get("projects") or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("project_name") or item.get("title")
        tech = item.get("stack") or item.get("tech") or item.get("technologies") or []
        if isinstance(tech, str):
            tech = [tech]
        description = item.get("description") or item.get("detail") or item.get("summary")
        if not (name or description):
            continue
        briefs.append(
            ResumeProjectOut(
                name=str(name) if name else None,
                role=item.get("role"),
                tech=[str(value) for value in tech][:8],
                description=description,
            )
        )
    return briefs[:5]


async def _match_gap(
    db: AsyncSession, job_id: int, candidate_id: int
) -> MatchGapOut | None:
    """取最近一次匹配结果，供详情与面试题引用缺口"""
    row = (
        await db.execute(
            select(MatchResult)
            .where(
                MatchResult.job_id == job_id,
                MatchResult.candidate_id == candidate_id,
            )
            .order_by(MatchResult.create_time.desc(), MatchResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        return None

    features = (row.detail or {}).get("features") or {}
    return MatchGapOut(
        score=row.score,
        summary=row.summary,
        matched_must=features.get("matched_must") or [],
        missing_must=features.get("missing_must") or [],
        matched_nice=features.get("matched_nice") or [],
        missing_nice=features.get("missing_nice") or [],
        years_gap=features.get("years_gap"),
        jd_min_years=features.get("jd_min_years"),
        candidate_years=features.get("candidate_years"),
    )


async def _card(db: AsyncSession, application: Application) -> ApplicationCardOut:
    candidate = await db.get(Candidate, application.candidate_id)
    return ApplicationCardOut(
        id=application.id,
        job_id=application.job_id,
        candidate_id=application.candidate_id,
        candidate_name=candidate.name if candidate else None,
        candidate_title=candidate.current_title if candidate else None,
        candidate_company=candidate.current_company if candidate else None,
        years_experience=(
            float(candidate.years_experience)
            if candidate and candidate.years_experience is not None
            else None
        ),
        status=application.status,
        status_label=label(application.status),
        match_score=float(application.match_score) if application.match_score is not None else None,
        days_in_stage=_days_in_stage(application.stage_entered_at),
        allowed_next=sorted(APP_TRANSITIONS.get(application.status, set())),
    )


async def build_detail(db: AsyncSession, application: Application) -> ApplicationDetailOut:
    candidate = await db.get(Candidate, application.candidate_id)
    job = await db.get(Job, application.job_id)
    resume = await _primary_resume(db, application.candidate_id)
    card = await _card(db, application)

    return ApplicationDetailOut(
        **card.model_dump(),
        job_title=job.title if job else None,
        job_department=job.department if job else None,
        candidate_city=candidate.city if candidate else None,
        candidate_education=candidate.education_level if candidate else None,
        candidate_skills=list(candidate.skills or []) if candidate else [],
        projects=_project_briefs(resume.structured if resume else None),
        applied_at=application.applied_at,
        stage_entered_at=application.stage_entered_at,
        rejected_reason=application.rejected_reason,
        offer_salary=application.offer_salary,
        hired_at=application.hired_at,
        match=await _match_gap(db, application.job_id, application.candidate_id),
        create_time=application.create_time,
        update_time=application.update_time,
    )


async def list_board(db: AsyncSession, job: Job) -> BoardOut:
    rows = (
        await db.execute(
            select(Application)
            .where(Application.job_id == job.id)
            .order_by(Application.stage_entered_at.desc(), Application.id.desc())
        )
    ).scalars().all()

    candidate_ids = {row.candidate_id for row in rows}
    candidates: dict[int, Candidate] = {}
    if candidate_ids:
        candidate_rows = (
            await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
        ).scalars().all()
        candidates = {candidate.id: candidate for candidate in candidate_rows}

    columns: list[BoardColumnOut] = []
    for status_value in APP_STATUSES:
        items: list[ApplicationCardOut] = []
        for row in rows:
            if row.status != status_value:
                continue
            candidate = candidates.get(row.candidate_id)
            items.append(
                ApplicationCardOut(
                    id=row.id,
                    job_id=row.job_id,
                    candidate_id=row.candidate_id,
                    candidate_name=candidate.name if candidate else None,
                    candidate_title=candidate.current_title if candidate else None,
                    candidate_company=candidate.current_company if candidate else None,
                    years_experience=(
                        float(candidate.years_experience)
                        if candidate and candidate.years_experience is not None
                        else None
                    ),
                    status=row.status,
                    status_label=label(row.status),
                    match_score=(
                        float(row.match_score) if row.match_score is not None else None
                    ),
                    days_in_stage=_days_in_stage(row.stage_entered_at),
                    allowed_next=sorted(APP_TRANSITIONS.get(row.status, set())),
                )
            )
        # 分数高的排前面，分数相同按进入阶段时间倒序
        items.sort(key=lambda item: (-(item.match_score or 0), -item.days_in_stage, item.id))
        columns.append(
            BoardColumnOut(status=status_value, label=label(status_value), items=items)
        )

    return BoardOut(job_id=job.id, job_title=job.title, columns=columns)


async def create_application(
    db: AsyncSession, data, user_id: int
) -> ApplicationDetailOut:
    job = await db.get(Job, data.job_id)
    if job is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="职位不存在")

    candidate = await db.get(Candidate, data.candidate_id)
    if candidate is None or candidate.is_deleted:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="候选人不存在")

    existing = (
        await db.execute(
            select(Application).where(
                Application.job_id == job.id,
                Application.candidate_id == candidate.id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=f"{candidate.name or '该候选人'} 已在「{job.title}」的流程中",
        )

    score = (
        await db.execute(
            select(MatchResult.score)
            .where(
                MatchResult.job_id == job.id,
                MatchResult.candidate_id == candidate.id,
            )
            .order_by(MatchResult.create_time.desc(), MatchResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    now = utcnow()
    application = Application(
        job_id=job.id,
        candidate_id=candidate.id,
        status=APP_NEW,
        source=data.source,
        match_score=score,
        applied_at=now,
        stage_entered_at=now,
        created_by=user_id,
        company_id=1,
    )
    db.add(application)
    await db.flush()

    db.add(
        ApplicationStageHistory(
            application_id=application.id,
            from_status=None,
            to_status=APP_NEW,
            operator_id=user_id,
            note="进入招聘流程",
        )
    )
    job.apply_count = (job.apply_count or 0) + 1

    await db.commit()
    await db.refresh(application)
    return await build_detail(db, application)


async def change_status(
    db: AsyncSession,
    application: Application,
    target: str,
    operator_id: int,
    note: str | None = None,
    offer_salary: int | None = None,
) -> ApplicationDetailOut:
    """流转状态：校验 → 更新 → 历史 → 通知（同一事务）"""
    if target not in APP_STATUSES:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST, detail=f"未知状态：{target}"
        )

    allowed = APP_TRANSITIONS.get(application.status, set())
    if target not in allowed:
        allowed_text = "、".join(label(value) for value in sorted(allowed)) or "无"
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=(
                f"状态非法：{label(application.status)} 不能直接转为 {label(target)}；"
                f"当前允许：{allowed_text}"
            ),
        )

    reason = (note or "").strip()
    if target == APP_REJECTED and not reason:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail="淘汰候选人必须填写原因",
        )

    from_status = application.status
    now = utcnow()
    duration = (
        int((now - application.stage_entered_at).total_seconds())
        if application.stage_entered_at
        else None
    )

    application.status = target
    application.stage_entered_at = now
    if target == APP_REJECTED:
        application.rejected_reason = reason
        application.rejected_by = operator_id
    elif target == APP_OFFER:
        if offer_salary is not None:
            application.offer_salary = offer_salary
    elif target == APP_HIRED:
        application.hired_at = now
        if from_status == APP_OFFER:
            application.offer_accepted_at = now

    db.add(
        ApplicationStageHistory(
            application_id=application.id,
            from_status=from_status,
            to_status=target,
            operator_id=operator_id,
            note=reason or None,
            duration_in_prev_status=duration,
        )
    )

    await notification_svc.notify_status_change(
        db,
        application=application,
        from_status=from_status,
        to_status=target,
        note=reason or None,
        operator_id=operator_id,
    )

    await db.commit()
    await db.refresh(application)
    return await build_detail(db, application)


async def get_timeline(db: AsyncSession, application: Application) -> TimelineOut:
    rows = (
        await db.execute(
            select(ApplicationStageHistory)
            .where(ApplicationStageHistory.application_id == application.id)
            .order_by(
                ApplicationStageHistory.create_time.asc(),
                ApplicationStageHistory.id.asc(),
            )
        )
    ).scalars().all()

    operator_ids = {row.operator_id for row in rows if row.operator_id}
    operator_names: dict[int, str] = {}
    if operator_ids:
        users = (
            await db.execute(select(User).where(User.id.in_(operator_ids)))
        ).scalars().all()
        operator_names = {user.id: user.name for user in users}

    return TimelineOut(
        items=[
            HistoryOut(
                id=row.id,
                from_status=row.from_status,
                from_label=label(row.from_status) if row.from_status else None,
                to_status=row.to_status,
                to_label=label(row.to_status),
                operator_id=row.operator_id,
                operator_name=operator_names.get(row.operator_id),
                note=row.note,
                duration_in_prev_status=row.duration_in_prev_status,
                create_time=row.create_time,
            )
            for row in rows
        ]
    )


async def transition_by_payload(
    db: AsyncSession, application_id: int, payload: ApplicationTransitionIn, user_id: int
) -> ApplicationDetailOut:
    application = await get_application_or_404(db, application_id)
    return await change_status(
        db,
        application,
        payload.to_status,
        user_id,
        note=payload.note,
        offer_salary=payload.offer_salary,
    )
