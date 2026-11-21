"""数据分析与成本监控 响应模型"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class OverviewOut(BaseModel):
    open_jobs: int = 0
    total_applications: int = 0
    pending_interview: int = 0
    hired: int = 0
    rejected: int = 0
    avg_cycle_days: float | None = None
    status_counts: dict[str, int] = {}


class FunnelStageOut(BaseModel):
    status: str
    label: str
    count: int = 0          # 到达过该阶段的人数（漏斗口径）
    current: int = 0        # 当前停留人数
    share: float = 0.0
    conversion: float | None = None


class ChannelOut(BaseModel):
    source: str
    total: int = 0
    interview: int = 0
    hired: int = 0
    rejected: int = 0
    conversion: float = 0.0


class CycleStageOut(BaseModel):
    stage: str
    label: str
    samples: int = 0
    avg_hours: float | None = None


class DashboardOut(BaseModel):
    overview: OverviewOut
    funnel: list[FunnelStageOut] = []
    channels: list[ChannelOut] = []
    cycle: list[CycleStageOut] = []
    generated_at: datetime


class AiCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    feature: str
    agent: str | None = None
    provider: str | None = None
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    currency: str = "CNY"
    duration_ms: int | None = None
    cache_hit: bool = False
    status: str = "success"
    error_reason: str | None = None
    job_id: int | None = None
    candidate_id: int | None = None
    user_id: int | None = None
    job_title: str | None = None
    create_time: datetime


class AiCallListOut(BaseModel):
    items: list[AiCallOut] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class FeatureCostOut(BaseModel):
    feature: str
    calls: int = 0
    tokens: int = 0
    cost: float = 0.0


class JobCostOut(BaseModel):
    job_id: int
    job_title: str
    calls: int = 0
    tokens: int = 0
    cost: float = 0.0


class CostSummaryOut(BaseModel):
    total_calls: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    today_cost: float = 0.0
    month_cost: float = 0.0
    budget: float = 0.0
    budget_ratio: float = 0.0
    budget_status: str = "ok"
    by_feature: list[FeatureCostOut] = []
    top_jobs: list[JobCostOut] = []
