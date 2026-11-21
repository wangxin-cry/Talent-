"""多 Agent 编排请求 / 响应模型（阶段九）"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

ORCHESTRATION_INTENTS = (
    "jd_generate",
    "resume_upload",
    "match",
    "interview",
    "advance_status",
    "analytics",
    "full_eval",
)


# ---------------------------------------------------------------- 请求
class OrchestrationRunIn(BaseModel):
    intent: str = Field(description="编排意图，见 /orchestration/intents")
    job_id: int | None = Field(default=None, description="职位 id")
    application_id: int | None = Field(default=None, description="应聘记录 id")
    candidate_id: int | None = Field(default=None, description="候选人 id")
    file_ids: list[int] = Field(default_factory=list, description="批量解析指定简历文件")
    to_status: str | None = Field(default=None, description="推进状态的目标状态")
    note: str | None = Field(default=None, max_length=1000)
    offer_salary: int | None = Field(default=None, ge=0, le=1000)

    top_n: int = Field(default=3, ge=1, le=10, description="一键评估取前 N 名")
    limit: int | None = Field(default=None, ge=1, le=200, description="批量解析上限")
    use_llm: bool = Field(default=False, description="是否允许子 Agent 调用 LLM")
    step_timeout: float | None = Field(
        default=None, ge=0.05, le=120, description="单步超时（秒），默认取全局配置"
    )

    # JD 生成参数
    title: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    keywords: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 轨迹
class TraceStepOut(BaseModel):
    step_no: int
    agent: str
    parent_step: int | None = None
    status: str
    degraded: bool = False
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    input_summary: dict = {}
    output_summary: dict = {}
    error_reason: str | None = None


class OrchestrationRunOut(BaseModel):
    trace_id: str
    intent: str
    intent_label: str
    status: str = "success"
    degraded: bool = False
    duration_ms: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    plan: list[str] = []
    steps: list[TraceStepOut] = []
    result: dict = {}


class TraceDetailOut(BaseModel):
    trace_id: str
    intent: str | None = None
    status: str = "success"
    degraded: bool = False
    duration_ms: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    steps: list[TraceStepOut] = []
    create_time: datetime | None = None


class TraceSummaryOut(BaseModel):
    trace_id: str
    intent: str | None = None
    status: str = "success"
    degraded: bool = False
    duration_ms: int = 0
    total_cost: float = 0.0
    step_count: int = 0
    create_time: datetime | None = None


class TraceListOut(BaseModel):
    items: list[TraceSummaryOut] = []
    total: int = 0


class IntentOut(BaseModel):
    intent: str
    label: str
    agents: list[str] = []
    description: str = ""


class IntentListOut(BaseModel):
    items: list[IntentOut] = []
