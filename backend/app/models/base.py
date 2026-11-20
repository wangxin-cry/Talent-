"""
模型基类与公共字段

约定：
- 所有表主键 id（BIGINT 自增）
- 多数表带 create_time / update_time（UTC）
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class IdMixin:
    """自增主键"""

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)


class TimestampMixin:
    """创建/更新时间"""

    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class CompanyScopedMixin:
    """公司隔离字段（单公司部署恒为 1，为多租户预留）"""

    company_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, default=1)
