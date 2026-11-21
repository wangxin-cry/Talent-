"""人岗匹配相关请求/响应模型"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MatchItemOut(BaseModel):
    """匹配结果列表项"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    candidate_id: int
    resume_id: int | None = None
    score: float
    skill_score: float | None = None
    exp_score: float | None = None
    edu_score: float | None = None
    other_score: float | None = None
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    summary: str | None = None
    feedback: str | None = None
    create_time: datetime
    candidate_name: str | None = None


class MatchDetailOut(MatchItemOut):
    """匹配结果详情（含完整理由明细）"""
    detail: dict = {}


class MatchListOut(BaseModel):
    items: list[MatchItemOut]
    total: int
    job_id: int
    job_title: str


class MatchFeedbackIn(BaseModel):
    feedback: str  # fit / unfit

class MatchTriggerOut(BaseModel):
    job_id: int
    matched_count: int
    cached_count: int
    computed_count: int = 0
    items: list[MatchItemOut]