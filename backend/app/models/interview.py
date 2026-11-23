"""
面试安排 / 面试评估 / 公开投递追踪（PRD RA-02、IA-02、IA-03、CE-01、CE-02）

独立建表，避免对既有表做 ALTER，SQLite / PostgreSQL 都能直接 create_all。
"""
from __future__ import annotations

import secrets
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin

INTERVIEW_MODES = ("online", "onsite", "phone")
RECOMMENDATIONS = ("strong_hire", "hire", "hold", "no_hire")
RECOMMENDATION_LABELS = {
    "strong_hire": "强烈推荐",
    "hire": "推荐",
    "hold": "待定",
    "no_hire": "不推荐",
}


def new_tracking_token() -> str:
    return secrets.token_urlsafe(18)


class InterviewSchedule(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """面试安排：一个投递一条（可改期）"""

    __tablename__ = "interview_schedule"

    application_id: Mapped[int] = mapped_column(
        BigInteger, index=True, unique=True, nullable=False, comment="投递 id"
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, comment="面试开始时间（UTC）")
    duration_minutes: Mapped[int] = mapped_column(Integer, default=60, nullable=False, comment="时长（分钟）")
    mode: Mapped[str] = mapped_column(
        String(20), default="online", nullable=False, comment="online线上 / onsite现场 / phone电话"
    )
    location: Mapped[str | None] = mapped_column(String(255), comment="地点或会议链接")
    interviewer: Mapped[str | None] = mapped_column(String(100), comment="面试官")
    note: Mapped[str | None] = mapped_column(Text, comment="面试备注")
    created_by: Mapped[int | None] = mapped_column(BigInteger, comment="安排人 user_id")


class InterviewFeedback(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """面试评估记录：多维度评分 + 结论 + 评语"""

    __tablename__ = "interview_feedback"

    application_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="投递 id")
    interviewer_id: Mapped[int | None] = mapped_column(BigInteger, comment="面试官 user_id")
    interviewer_name: Mapped[str | None] = mapped_column(String(100), comment="面试官姓名")
    round: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="面试轮次")
    scores: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False,
                                          comment="维度评分：{dimension_key: 1~5}")
    overall_rating: Mapped[float | None] = mapped_column(Float, comment="综合评分 1~5")
    recommendation: Mapped[str | None] = mapped_column(
        String(20), comment="strong_hire / hire / hold / no_hire"
    )
    comment: Mapped[str | None] = mapped_column(Text, comment="面试评语")


class ApplicationTracking(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """公开投递进度查询凭证：凭 token + 邮箱查看进度"""

    __tablename__ = "application_tracking"

    application_id: Mapped[int] = mapped_column(
        BigInteger, index=True, unique=True, nullable=False, comment="投递 id"
    )
    token: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, default=new_tracking_token
    )
    email_hash: Mapped[str | None] = mapped_column(String(64), index=True, comment="投递邮箱 sha256（校验用）")
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近查询时间")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否有效")
