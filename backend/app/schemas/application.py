"""招聘流程 / 通知 / 面试题 请求与响应模型"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------- 请求
class ApplicationCreateIn(BaseModel):
    job_id: int
    candidate_id: int
    source: str | None = Field(default=None, max_length=30)


class ApplicationTransitionIn(BaseModel):
    to_status: str
    note: str | None = Field(default=None, max_length=1000)
    offer_salary: int | None = Field(default=None, ge=0, le=1000)


class QuestionGenerateIn(BaseModel):
    use_llm: bool = False
    use_rag: bool | None = Field(
        default=None, description="是否用知识库增强；空则跟随全局 RAG 开关"
    )
    force: bool = Field(default=False, description="忽略缓存重新生成")


# ---------------------------------------------------------------- 看板
class ApplicationCardOut(BaseModel):
    id: int
    job_id: int
    candidate_id: int
    candidate_name: str | None = None
    candidate_title: str | None = None
    candidate_company: str | None = None
    years_experience: float | None = None
    status: str
    status_label: str
    match_score: float | None = None
    days_in_stage: int = 0
    allowed_next: list[str] = []


class BoardColumnOut(BaseModel):
    status: str
    label: str
    items: list[ApplicationCardOut] = []


class BoardOut(BaseModel):
    job_id: int
    job_title: str
    columns: list[BoardColumnOut] = []


# ---------------------------------------------------------------- 详情
class ResumeProjectOut(BaseModel):
    name: str | None = None
    role: str | None = None
    tech: list[str] = []
    description: str | None = None


class MatchGapOut(BaseModel):
    score: float | None = None
    summary: str | None = None
    matched_must: list[str] = []
    missing_must: list[str] = []
    matched_nice: list[str] = []
    missing_nice: list[str] = []
    years_gap: float | None = None
    jd_min_years: float | None = None
    candidate_years: float | None = None


class ApplicationDetailOut(ApplicationCardOut):
    job_title: str | None = None
    job_department: str | None = None
    candidate_city: str | None = None
    candidate_education: str | None = None
    candidate_skills: list[str] = []
    projects: list[ResumeProjectOut] = []
    applied_at: datetime | None = None
    stage_entered_at: datetime | None = None
    rejected_reason: str | None = None
    offer_salary: int | None = None
    hired_at: datetime | None = None
    match: MatchGapOut | None = None
    create_time: datetime
    update_time: datetime


class HistoryOut(BaseModel):
    id: int
    from_status: str | None = None
    from_label: str | None = None
    to_status: str
    to_label: str
    operator_id: int | None = None
    operator_name: str | None = None
    note: str | None = None
    duration_in_prev_status: int | None = None
    create_time: datetime


class TimelineOut(BaseModel):
    items: list[HistoryOut] = []


# ---------------------------------------------------------------- 面试题
class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category: str
    question: str
    looking_for: str | None = None
    reference: str | None = None
    follow_up: str | None = None
    sort_order: int = 0
    source: str = "template"


class QuestionSetOut(BaseModel):
    application_id: int
    cached: bool = False
    source: str = "none"
    total: int = 0
    rag_used: bool = False
    rag_sources: list[dict] = []
    questions: list[QuestionOut] = []


# ---------------------------------------------------------------- 通知
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int | None = None
    candidate_id: int | None = None
    candidate_name: str | None = None
    channel: str
    template: str
    subject: str | None = None
    body: str | None = None
    status: str
    create_time: datetime
    read_at: datetime | None = None


class NotificationListOut(BaseModel):
    items: list[NotificationOut] = []
    total: int = 0
    unread: int = 0


class UnreadCountOut(BaseModel):
    unread: int
