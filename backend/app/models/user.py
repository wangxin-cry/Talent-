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
from app.models.base import IdMixin, TimestampMixin

ROLE_RECRUITER = "recruiter"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"
ROLE_SUPERADMIN = "superadmin"  # 平台超管：跨公司管理，不参与业务数据

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
STATUS_DELETED = "deleted"


class User(IdMixin, TimestampMixin, Base):
    """用户"""

    __tablename__ = "user"
    __table_args__ = (Index("ix_user_company_role", "company_id", "role"),)

    # 所属公司；平台超管为空
    company_id: Mapped[int | None] = mapped_column(BigInteger, index=True, nullable=True)

    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50), comment="展示昵称，不影响登录账号")
    bio: Mapped[str | None] = mapped_column(String(255), comment="个人简介")
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default=ROLE_RECRUITER, nullable=False, index=True)
    department: Mapped[str | None] = mapped_column(String(100), index=True, comment="所属部门，manager 的数据范围依据")
    phone: Mapped[str | None] = mapped_column(String(30))
    avatar_key: Mapped[str | None] = mapped_column(String(500), comment="头像对象存储 key；URL 由后端生成")
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
