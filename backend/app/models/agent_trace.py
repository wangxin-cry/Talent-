"""编排轨迹表（阶段九）

一次多 Agent 编排共享一个 trace_id，每个 Agent 每一步写一行。
只存摘要不存全文；与 ai_call 通过 trace_id 关联（trace 记流程，ai_call 记模型调用）。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, utcnow

# 步骤状态
TRACE_SUCCESS = "success"
TRACE_FAILED = "failed"
TRACE_TIMEOUT = "timeout"
TRACE_SKIPPED = "skipped"
TRACE_DEGRADED = "degraded"

# Agent 名称（与前端轨迹面板、ai_call.agent 保持一致）
AGENT_MANAGER = "Manager"
AGENT_JD_WRITER = "JDWriter"
AGENT_RESUME_PARSER = "ResumeParser"
AGENT_MATCH_ENGINE = "MatchEngine"
AGENT_INTERVIEW = "InterviewAssistant"
AGENT_WORKFLOW = "WorkflowAuto"
AGENT_ANALYTICS = "Analytics"


class AgentTrace(IdMixin, Base):
    """一次编排中某一步的执行记录"""

    __tablename__ = "agent_trace"
    __table_args__ = (
        Index("ix_agent_trace_trace_step", "trace_id", "step_no"),
        Index("ix_agent_trace_agent_time", "agent", "create_time"),
        Index("ix_agent_trace_create", "create_time"),
    )

    trace_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="一次编排的共享 id"
    )
    session_id: Mapped[int | None] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), comment="来源会话（页面触发时为空）"
    )
    step_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="步骤序号")
    agent: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="Manager/JDWriter/ResumeParser/MatchEngine/InterviewAssistant/WorkflowAuto/Analytics",
    )
    parent_step: Mapped[int | None] = mapped_column(Integer, comment="父步骤（子任务归属）")
    intent: Mapped[str | None] = mapped_column(String(50), comment="本次编排意图")

    input_summary: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False, comment="输入摘要（不含全文）"
    )
    input_hash: Mapped[str | None] = mapped_column(String(64), comment="输入指纹")
    output_summary: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False, comment="输出摘要"
    )

    status: Mapped[str] = mapped_column(
        String(20), default=TRACE_SUCCESS, nullable=False,
        comment="success/failed/timeout/skipped/degraded",
    )
    degraded: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否降级"
    )
    error_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因")

    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="耗时（毫秒）")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="输入 token")
    tokens_out: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="输出 token")
    cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=0, nullable=False, comment="本步费用（元）"
    )
    tool_calls: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="本步调用的工具列表"
    )

    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True, comment="记录时间"
    )
