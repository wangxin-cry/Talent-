"""
模型基类与公共字段

约定：
- 所有表主键 id（BIGINT 自增）
- 多数表带 create_time / update_time（UTC）
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.tenant import get_company_id

from sqlalchemy import BigInteger, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class IdMixin:
    """自增主键"""

    # SQLite 只有 INTEGER PRIMARY KEY 才能自增，故用 variant 降级类型
    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True
    )


class TimestampMixin:
    """创建/更新时间"""

    create_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), nullable=False
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, server_default=func.now(), nullable=False
    )


class CompanyScopedMixin:
    """公司隔离字段

    默认取请求/任务上下文中的公司；仅在没有上下文（如初始化脚本）时回落到 1。
    """

    company_id: Mapped[int] = mapped_column(
        BigInteger, index=True, nullable=False, default=lambda: get_company_id() or 1
    )
