from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InterviewScheduleIn(BaseModel):
    scheduled_at: datetime = Field(description="面试开始时间（UTC）")
    duration_minutes: int = Field(default=60, ge=15, le=480)
    mode: str = Field(default="online", pattern="^(online|onsite|phone)$")
    location: str | None = Field(default=None, max_length=255)
    interviewer: str | None = Field(default=None, max_length=100)
    note: str | None = None


class InterviewScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    scheduled_at: datetime
    duration_minutes: int
    mode: str
    location: str | None = None
    interviewer: str | None = None
    note: str | None = None
    created_by: int | None = None
    create_time: datetime
    update_time: datetime


class FeedbackIn(BaseModel):
    round: int = Field(default=1, ge=1, le=10)
    scores: dict[str, int] = Field(default_factory=dict)
    overall_rating: float | None = Field(default=None, ge=1, le=5)
    recommendation: str | None = Field(default=None, pattern="^(strong_hire|hire|hold|no_hire)$")
    comment: str | None = None


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    interviewer_id: int | None = None
    interviewer_name: str | None = None
    round: int
    scores: dict = Field(default_factory=dict)
    overall_rating: float | None = None
    recommendation: str | None = None
    recommendation_label: str | None = None
    comment: str | None = None
    create_time: datetime


class FeedbackSummaryOut(BaseModel):
    total: int = 0
    average_rating: float | None = None
    recommendation: str | None = None
    recommendation_label: str | None = None
    items: list[FeedbackOut] = []


class EvaluationDimensionOut(BaseModel):
    key: str
    name: str
    description: str


class EvaluationTemplateOut(BaseModel):
    title: str = "结构化面试评估表"
    scale: int = 5
    dimensions: list[EvaluationDimensionOut] = []
    recommendations: list[dict[str, str]] = []


# ---------------------------------------------------------------- 公开投递
class PublicJobOut(BaseModel):
    id: int
    title: str
    department: str | None = None
    location: str | None = None
    work_mode: str | None = None
    employment_type: str
    headcount: int = 1
    education_level: str | None = None
    min_years: float | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    description: str | None = None
    requirements: str | None = None
    published_at: datetime | None = None


class PublicJobListOut(BaseModel):
    total: int
    items: list[PublicJobOut]


class ApplyResultOut(BaseModel):
    application_id: int
    tracking_token: str
    job_title: str
    message: str = "投递成功，请保存查询凭证以跟踪进度"


class ProgressStepOut(BaseModel):
    status: str
    label: str
    reached: bool = False
    current: bool = False
    time: datetime | None = None


class ProgressOut(BaseModel):
    job_title: str
    candidate_name: str | None = None
    status: str
    status_label: str
    applied_at: datetime | None = None
    steps: list[ProgressStepOut] = []
    interview_at: datetime | None = None
    message: str | None = None
