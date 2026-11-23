"""API Key：给外部系统/脚本调用 TalentMatch 的长期凭证"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin


class ApiKey(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """API Key 只存哈希，明文只在创建时返回一次"""

    __tablename__ = "api_key"
    __table_args__ = (Index("ix_api_key_company_user", "company_id", "user_id"),)

    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="归属用户")
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="用途名称")
    prefix: Mapped[str] = mapped_column(String(20), nullable=False, comment="展示用前缀")
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, comment="密钥 sha256")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, comment="最近使用时间")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, comment="过期时间，NULL 表示不过期")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, comment="吊销时间")
