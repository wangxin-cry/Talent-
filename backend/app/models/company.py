"""
公司（租户）

一家公司一套数据：职位、候选人、投递、面试、通知、对话、知识库、
AI 成本、系统配置、审计日志都通过 company_id 隔离。
"""
from __future__ import annotations

import secrets

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"

# 去掉易混淆字符（0/O、1/I），方便口头传递邀请码
_INVITE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_invite_code() -> str:
    return "".join(secrets.choice(_INVITE_ALPHABET) for _ in range(8))


def generate_slug() -> str:
    """公开招聘页短标识：/careers/<slug>"""
    return "c" + secrets.token_hex(4)


class Company(IdMixin, TimestampMixin, Base):
    """公司"""

    __tablename__ = "company"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    invite_code: Mapped[str] = mapped_column(String(16), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_ACTIVE, nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, comment="首位管理员用户 id，建司时写入"
    )
    contact_email: Mapped[str | None] = mapped_column(String(255), comment="公司联系邮箱")
