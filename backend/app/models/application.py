"""
应聘记录与状态流转历史（阶段六）

状态机（docs §4 状态机）：
    new → screening → interview → offer → hired
    任意非终态 → rejected（必须填写原因）
    hired / rejected 为终态

application 一个 (job_id, candidate_id) 只有一条记录；
application_stage_history 只追加不更新，每次流转写一条。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin, utcnow

APP_NEW = "new"
APP_SCREENING = "screening"
APP_INTERVIEW = "interview"
APP_OFFER = "offer"
APP_HIRED = "hired"
APP_REJECTED = "rejected"

# 看板列顺序
APP_STATUSES = (APP_NEW, APP_SCREENING, APP_INTERVIEW, APP_OFFER, APP_HIRED, APP_REJECTED)

APP_STATUS_LABELS = {
    APP_NEW: "新申请",
    APP_SCREENING: "筛选中",
    APP_INTERVIEW: "面试中",
    APP_OFFER: "Offer",
    APP_HIRED: "已入职",
    APP_REJECTED: "已淘汰",
}

# 只允许沿箭头前进；任意非终态可淘汰
APP_TRANSITIONS: dict[str, set[str]] = {
    APP_NEW: {APP_SCREENING, APP_REJECTED},
    APP_SCREENING: {APP_INTERVIEW, APP_REJECTED},
    APP_INTERVIEW: {APP_OFFER, APP_REJECTED},
    APP_OFFER: {APP_HIRED, APP_REJECTED},
    APP_HIRED: set(),
    APP_REJECTED: set(),
}


class Application(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """应聘记录：谁投了哪个职位、当前走到哪一步"""

    __tablename__ = "application"
    __table_args__ = (
        # 同一职位同一候选人只允许一条应聘记录
        UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),
        Index("ix_application_job_status", "job_id", "status"),
        Index("ix_application_stage_entered", "stage_entered_at"),
    )

    job_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="应聘职位 id")
    candidate_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True,
                                              comment="应聘候选人 id")
    status: Mapped[str] = mapped_column(String(20), default=APP_NEW, nullable=False, index=True,
                                         comment="new/screening/interview/offer/hired/rejected")
    source: Mapped[str | None] = mapped_column(String(30), comment="投递来源渠道")
    match_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2),
                                                         comment="进入流程时的匹配分快照")

    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False,
                                                  comment="投递时间")
    stage_entered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False,
                                                        comment="进入当前阶段的时间，看板停留时长依赖它")

    rejected_reason: Mapped[str | None] = mapped_column(Text, comment="淘汰原因")
    rejected_by: Mapped[int | None] = mapped_column(BigInteger, comment="淘汰操作人 user_id")
    offer_salary: Mapped[int | None] = mapped_column(Integer, comment="Offer 月薪（K）")
    offer_accepted_at: Mapped[datetime | None] = mapped_column(DateTime, comment="接受 Offer 时间")
    hired_at: Mapped[datetime | None] = mapped_column(DateTime, comment="入职时间")
    created_by: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="创建人 user_id")


class ApplicationStageHistory(IdMixin, Base):
    """状态流转历史：只追加，不更新不删除"""

    __tablename__ = "application_stage_history"
    __table_args__ = (
        Index("ix_stage_history_app_time", "application_id", "create_time"),
        Index("ix_stage_history_to_status", "to_status"),
    )

    application_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True,
                                                 comment="所属应聘记录")
    from_status: Mapped[str | None] = mapped_column(String(20), comment="变更前状态，首次进入为空")
    to_status: Mapped[str] = mapped_column(String(20), nullable=False, comment="变更后状态")
    operator_id: Mapped[int | None] = mapped_column(BigInteger, comment="操作人 user_id，系统触发为空")
    note: Mapped[str | None] = mapped_column(Text, comment="备注，淘汰时写原因")
    duration_in_prev_status: Mapped[int | None] = mapped_column(Integer,
                                                                 comment="在上一阶段停留秒数（冗余）")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False,
                                                   comment="变更时间")
