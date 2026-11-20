"""
技能词表模型

对应 docs/TalentMatch_数据库设计_V1.md §3.2.1：
- name 为归一后的标准名（如 Kubernetes）
- aliases 存别名数组（K8s / k8s / kube）
- 用于 JD、简历、匹配的技能归一
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin

CATEGORY_LANGUAGE = "language"
CATEGORY_FRAMEWORK = "framework"
CATEGORY_DATABASE = "database"
CATEGORY_MIDDLEWARE = "middleware"
CATEGORY_TOOL = "tool"
CATEGORY_SOFT = "soft"


class Skill(IdMixin, TimestampMixin, Base):
    """技能标准名与别名"""

    __tablename__ = "skill"

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), index=True)
    parent_id: Mapped[int | None] = mapped_column(BigInteger)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
