"""审计日志：敏感数据访问与关键操作留痕"""
from __future__ import annotations

from sqlalchemy import BigInteger, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin


class AuditLog(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    __tablename__ = "audit_log"

    action: Mapped[str] = mapped_column(String(50), index=True, nullable=False,
                                         comment="动作：resume.upload / resume.parsed / resume.download / candidate.update ...")
    target_type: Mapped[str] = mapped_column(String(50), index=True, nullable=False,
                                              comment="对象类型：candidate / resume_file / job ...")
    target_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="对象 id")
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False, comment="动作明细")
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="操作人 user_id")
