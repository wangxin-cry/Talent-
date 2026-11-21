"""招聘流程接口：看板、流转、时间线、面试题"""
from __future__ import annotations

from fastapi import APIRouter, Query, status

from app.core.deps import CurrentUser, DbSession
from app.schemas.application import (
    ApplicationCreateIn,
    ApplicationDetailOut,
    ApplicationTransitionIn,
    BoardOut,
    QuestionGenerateIn,
    QuestionSetOut,
    TimelineOut,
)
from app.services import interview_questions as question_svc
from app.services import pipeline
from app.services.job import get_job_or_404

router = APIRouter(prefix="/applications", tags=["招聘流程"])


@router.post(
    "",
    response_model=ApplicationDetailOut,
    status_code=status.HTTP_201_CREATED,
    summary="把候选人加入职位流程",
)
async def create_api(
    data: ApplicationCreateIn, db: DbSession, user: CurrentUser
) -> ApplicationDetailOut:
    return await pipeline.create_application(db, data, user.id)


@router.get("/board", response_model=BoardOut, summary="招聘流程看板（按状态分列）")
async def board_api(
    db: DbSession,
    _: CurrentUser,
    job_id: int = Query(..., description="职位 id"),
) -> BoardOut:
    job = await get_job_or_404(db, job_id)
    return await pipeline.list_board(db, job)


@router.get("/{application_id}", response_model=ApplicationDetailOut, summary="应聘详情")
async def detail_api(
    application_id: int, db: DbSession, _: CurrentUser
) -> ApplicationDetailOut:
    application = await pipeline.get_application_or_404(db, application_id)
    return await pipeline.build_detail(db, application)


@router.post(
    "/{application_id}/transition",
    response_model=ApplicationDetailOut,
    summary="流转状态（非法跳转直接拒绝）",
)
async def transition_api(
    application_id: int,
    payload: ApplicationTransitionIn,
    db: DbSession,
    user: CurrentUser,
) -> ApplicationDetailOut:
    return await pipeline.transition_by_payload(db, application_id, payload, user.id)


@router.get(
    "/{application_id}/timeline",
    response_model=TimelineOut,
    summary="状态流转时间线",
)
async def timeline_api(
    application_id: int, db: DbSession, _: CurrentUser
) -> TimelineOut:
    application = await pipeline.get_application_or_404(db, application_id)
    return await pipeline.get_timeline(db, application)


@router.get(
    "/{application_id}/questions",
    response_model=QuestionSetOut,
    summary="读取已生成的面试题",
)
async def list_questions_api(
    application_id: int, db: DbSession, _: CurrentUser
) -> QuestionSetOut:
    application = await pipeline.get_application_or_404(db, application_id)
    return await question_svc.list_questions(db, application)


@router.post(
    "/{application_id}/questions",
    response_model=QuestionSetOut,
    summary="生成面试题（6~8 题，引用具体项目/缺口）",
)
async def generate_questions_api(
    application_id: int,
    payload: QuestionGenerateIn,
    db: DbSession,
    _: CurrentUser,
) -> QuestionSetOut:
    application = await pipeline.get_application_or_404(db, application_id)
    return await question_svc.generate_questions(db, application, use_llm=payload.use_llm)
