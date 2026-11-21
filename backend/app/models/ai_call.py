"""AI 调用计量表（阶段七）

每次真实 LLM 调用写一行：模型、输入/输出 token、费用、耗时、状态。
走缓存不产生调用，因此不写台账；表的 cache_hit 字段预留给显式记录的场景。
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
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, utcnow

AI_STATUS_SUCCESS = "success"
AI_STATUS_FAILED = "failed"
AI_STATUS_SKIPPED = "skipped"


class AiCall(IdMixin, CompanyScopedMixin, Base):
    """一次 LLM 调用的明细账"""

    __tablename__ = "ai_call"
    __table_args__ = (
        Index("ix_ai_call_company_time", "company_id", "create_time"),
        Index("ix_ai_call_feature_time", "feature", "create_time"),
        Index("ix_ai_call_job_time", "job_id", "create_time"),
        Index("ix_ai_call_trace", "trace_id"),
    )

    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="触发人")
    job_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="关联职位")
    candidate_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="关联候选人")

    feature: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="resume_parse/resume_ocr/jd_generate/match_explain/interview_generate",
    )
    agent: Mapped[str | None] = mapped_column(String(50), comment="触发该调用的 Agent")
    provider: Mapped[str | None] = mapped_column(String(50), comment="厂商标识")
    model: Mapped[str | None] = mapped_column(String(100), comment="模型名")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="输入 token")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="输出 token")
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="合计 token")

    cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=0, nullable=False, comment="费用（元）"
    )
    currency: Mapped[str] = mapped_column(String(10), default="CNY", nullable=False, comment="币种")

    duration_ms: Mapped[int | None] = mapped_column(Integer, comment="耗时（毫秒）")
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                             comment="是否缓存命中；命中时 cost=0")
    status: Mapped[str] = mapped_column(String(20), default=AI_STATUS_SUCCESS, nullable=False,
                                         comment="success/failed/skipped")
    error_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因")
    trace_id: Mapped[str | None] = mapped_column(String(64), comment="关联编排轨迹")

    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True, comment="调用时间"
    )
