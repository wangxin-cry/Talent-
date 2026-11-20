"""
用户模型（平台内部账号）

对应 docs/TalentMatch_数据库设计_V1.md §3.1.2：
- 候选人不是这张表的用户
- password 只存 bcrypt 哈希
- role 是权限唯一来源（recruiter / manager / admin）
- 邮箱验证用 email_verified_at 记录（NULL 表示未验证）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin

ROLE_RECRUITER = "recruiter"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"


class User(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """用户"""

    __tablename__ = "user"
    __table_args__ = (Index("ix_user_company_role", "company_id", "role"),)

    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_RECRUITER, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=STATUS_ACTIVE, nullable=False, index=True)

    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    login_fail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)
    # 令牌版本：登出 / 改密时 +1，使已签发的 JWT 立即失效
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None
