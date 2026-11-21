"""站内通知记录（阶段六）"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, utcnow

NOTIF_CHANNEL_INAPP = "inapp"
NOTIF_CHANNEL_EMAIL = "email"

NOTIF_PENDING = "pending"
NOTIF_SENT = "sent"
NOTIF_FAILED = "failed"
NOTIF_READ = "read"


class Notification(IdMixin, CompanyScopedMixin, Base):
    """站内通知：状态流转时写入，通知中心展示"""

    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_user_status_time", "user_id", "status", "create_time"),
        Index("ix_notification_application", "application_id"),
    )

    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="接收人 user_id")
    candidate_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="相关候选人")
    application_id: Mapped[int | None] = mapped_column(BigInteger, index=True,
                                                        comment="相关应聘记录")
    channel: Mapped[str] = mapped_column(String(20), default=NOTIF_CHANNEL_INAPP, nullable=False,
                                          comment="inapp/email/sms/webhook")
    template: Mapped[str] = mapped_column(String(50), nullable=False,
                                           comment="resume_received/interview_invite/offer/rejected/status_update")
    subject: Mapped[str | None] = mapped_column(String(200), comment="标题")
    body: Mapped[str | None] = mapped_column(Text, comment="正文")
    to_addr: Mapped[str | None] = mapped_column(String(255), comment="收件地址（脱敏）")
    status: Mapped[str] = mapped_column(String(20), default=NOTIF_SENT, nullable=False, index=True,
                                         comment="pending/sent/failed/read")
    error_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, comment="发送时间")
    read_at: Mapped[datetime | None] = mapped_column(DateTime, comment="已读时间")
    create_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False,
                                                   comment="创建时间")
