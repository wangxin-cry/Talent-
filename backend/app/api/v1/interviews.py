"""面试安排 / 评估 / 日历导出接口（RA-02、IA-02、IA-03）"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, status
from fastapi.responses import Response

from app.core.deps import CurrentUser, DbSession
from app.models.candidate import Candidate
from app.models.job import Job
from app.schemas.interview import (
    EvaluationTemplateOut,
    FeedbackIn,
    FeedbackOut,
    FeedbackSummaryOut,
    InterviewScheduleIn,
    InterviewScheduleOut,
)
from app.services import interviews as interview_svc
from app.services import pipeline, scope

router = APIRouter(tags=["面试安排与评估"])


async def _application(db, user, application_id: int):
    """取投递并做数据权限校验（与其它流程接口一致）"""
    application = await pipeline.get_application_or_404(db, application_id)
    await scope.ensure_application_access(db, user, application)
    return application


@router.get(
    "/interviews/evaluation-template",
    response_model=EvaluationTemplateOut,
    summary="结构化面试评估模板",
)
async def evaluation_template(user: CurrentUser) -> EvaluationTemplateOut:
    return EvaluationTemplateOut(**interview_svc.EVALUATION_TEMPLATE)


@router.get(
    "/applications/{application_id}/interview-schedule",
    response_model=InterviewScheduleOut | None,
    summary="查看面试安排",
)
async def get_schedule_api(
    application_id: int, db: DbSession, user: CurrentUser
) -> InterviewScheduleOut | None:
    await _application(db, user, application_id)
    schedule = await interview_svc.get_schedule(db, application_id)
    return InterviewScheduleOut.model_validate(schedule) if schedule else None


@router.put(
    "/applications/{application_id}/interview-schedule",
    response_model=InterviewScheduleOut,
    summary="安排 / 修改面试（RA-02）",
)
async def upsert_schedule_api(
    application_id: int, data: InterviewScheduleIn, db: DbSession, user: CurrentUser
) -> InterviewScheduleOut:
    await _application(db, user, application_id)
    schedule = await interview_svc.upsert_schedule(db, application_id, data, user.id)
    return InterviewScheduleOut.model_validate(schedule)


@router.get(
    "/applications/{application_id}/interview.ics",
    summary="下载面试日历文件（.ics）",
    response_class=Response,
)
async def download_ics(
    application_id: int, db: DbSession, user: CurrentUser
) -> Response:
    application = await _application(db, user, application_id)
    schedule = await interview_svc.get_schedule(db, application_id)
    if schedule is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="尚未安排面试")

    job = await db.get(Job, application.job_id)
    candidate = await db.get(Candidate, application.candidate_id)
    content = interview_svc.build_ics(
        schedule,
        job_title=job.title if job else "面试",
        candidate_name=candidate.name if candidate else "候选人",
        application_id=application_id,
    )
    filename = f"interview-{application_id}.ics"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename={filename}; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.post(
    "/applications/{application_id}/feedbacks",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    summary="提交面试评估（IA-03）",
)
async def create_feedback_api(
    application_id: int, data: FeedbackIn, db: DbSession, user: CurrentUser
) -> FeedbackOut:
    await _application(db, user, application_id)
    feedback = await interview_svc.create_feedback(db, application_id, data, user)
    return FeedbackOut(**interview_svc.feedback_summary([feedback])["items"][0])


@router.get(
    "/applications/{application_id}/feedbacks",
    response_model=FeedbackSummaryOut,
    summary="面试评估记录与汇总",
)
async def list_feedbacks_api(
    application_id: int, db: DbSession, user: CurrentUser
) -> FeedbackSummaryOut:
    await _application(db, user, application_id)
    items = await interview_svc.list_feedbacks(db, application_id)
    return FeedbackSummaryOut(**interview_svc.feedback_summary(items))
