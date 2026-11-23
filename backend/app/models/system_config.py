"""系统配置：管理员可在后台调整的运行时参数"""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, BigInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin


class SystemConfig(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    __tablename__ = "system_config"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_system_config_company_key"),
    )

    key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    value: Mapped[Any] = mapped_column(JSON, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255))
    updated_by: Mapped[int | None] = mapped_column(BigInteger, comment="最后修改人 user_id")
