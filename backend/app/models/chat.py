"""对话式入口模型（阶段九½）

chat_session：一个招聘任务一个会话，保存当前业务上下文；
chat_message：消息文本 + 结构化结果卡片，刷新/切换会话后仍可回看。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin, utcnow

# 消息角色
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_SYSTEM = "system"

# 六类结果卡片（与前端约定一致）
CARD_UPLOAD = "upload"
CARD_PARSE_RESULT = "parse_result"
CARD_MATCH_RANK = "match_rank"
CARD_INTERVIEW = "interview"
CARD_CONFIRM = "confirm"
CARD_CHART = "chart"

CARD_TYPES = (
    CARD_UPLOAD,
    CARD_PARSE_RESULT,
    CARD_MATCH_RANK,
    CARD_INTERVIEW,
    CARD_CONFIRM,
    CARD_CHART,
)


class ChatSession(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """对话会话：保存当前职位 / 候选人等业务上下文"""

    __tablename__ = "chat_session"
    __table_args__ = (
        Index("ix_chat_session_user_last", "user_id", "last_message_at"),
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="会话归属用户"
    )
    title: Mapped[str | None] = mapped_column(String(100), comment="会话标题（可自动生成）")
    context_job_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="当前上下文职位 id"
    )
    context_candidate_id: Mapped[int | None] = mapped_column(
        BigInteger, comment="当前上下文候选人 id"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime, index=True, comment="最后消息时间，用于会话列表排序"
    )


class ChatMessage(IdMixin, Base):
    """对话消息：文本 + 卡片结构化数据"""

    __tablename__ = "chat_message"
    __table_args__ = (
        Index("ix_chat_message_session_time", "session_id", "create_time"),
        Index("ix_chat_message_trace", "trace_id"),
    )

    session_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="所属会话"
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="user/assistant/system"
    )
    content: Mapped[str | None] = mapped_column(Text, comment="文本内容")
    card_type: Mapped[str | None] = mapped_column(
        String(30), comment="upload/parse_result/match_rank/interview/confirm/chart"
    )
    card_data: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False, comment="卡片结构化数据"
    )
    intent: Mapped[str | None] = mapped_column(String(50), comment="本轮识别出的意图")
    trace_id: Mapped[str | None] = mapped_column(
        String(64), index=True, comment="关联编排轨迹"
    )
    tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="本轮 token")
    cost: Mapped[Decimal] = mapped_column(
        Numeric(10, 6), default=0, nullable=False, comment="本轮费用（元）"
    )
    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, comment="创建时间"
    )
