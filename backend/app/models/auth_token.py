"""
认证令牌（邮箱验证 / 密码重置）

设计要点：
- 库里只存 token 的 SHA-256，明文只出现在邮件链接里
- 一次性使用：consumed 时写 used_at
- 每次签发新 token 时把旧的未用 token 作废
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin

PURPOSE_VERIFY_EMAIL = "verify_email"
PURPOSE_RESET_PASSWORD = "reset_password"


class AuthToken(IdMixin, TimestampMixin, Base):
    """邮箱验证 / 密码重置令牌"""

    __tablename__ = "auth_token"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("user.id", ondelete="CASCADE"), index=True, nullable=False
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
