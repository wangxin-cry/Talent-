"""编排上下文（Context Bus）

一次编排内的共享状态：下游 Agent 直接读上游产出，不重复计算。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class StepRecord:
    """一步执行的记录（落库为 AgentTrace）"""

    step_no: int
    agent: str
    status: str = "success"
    degraded: bool = False
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    input_summary: dict = field(default_factory=dict)
    output_summary: dict = field(default_factory=dict)
    error_reason: str | None = None
    parent_step: int | None = None
    candidate_id: int | None = None
    tool_calls: list = field(default_factory=list)


@dataclass
class OrchestrationContext:
    """一次编排共享的上下文总线"""

    trace_id: str
    intent: str
    user_id: int

    job_id: int | None = None
    application_id: int | None = None
    candidate_id: int | None = None
    file_ids: list[int] = field(default_factory=list)
    to_status: str | None = None
    note: str | None = None
    offer_salary: int | None = None

    top_n: int = 3
    limit: int | None = None
    use_llm: bool = False
    step_timeout: float = 30.0

    # JD 生成参数
    title: str | None = None
    department: str | None = None
    location: str | None = None
    keywords: list[str] = field(default_factory=list)

    # ---- 调度 ----
    plan: list[str] = field(default_factory=list)
    cursor: int = 0

    # ---- 共享产出 ----
    job_snapshot: dict = field(default_factory=dict)
    resume_features: dict[int, dict] = field(default_factory=dict)
    match_results: list[dict] = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)

    steps: list[StepRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    started_at: float = field(default_factory=time.perf_counter)
    _next_no: int = 1

    @property
    def degraded(self) -> bool:
        return any(step.degraded for step in self.steps)

    @property
    def duration_ms(self) -> int:
        return int((time.perf_counter() - self.started_at) * 1000)

    def next_step_no(self) -> int:
        value = self._next_no
        self._next_no += 1
        return value

    def add_step(self, step: StepRecord) -> None:
        self.steps.append(step)
        if step.degraded or step.status != "success":
            if step.error_reason:
                self.errors.append(step.error_reason)

    def top_candidate_ids(self) -> list[int]:
        return [item["candidate_id"] for item in self.match_results][: self.top_n]
