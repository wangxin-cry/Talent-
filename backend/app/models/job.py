from __future__ import annotations
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin

STATUS_DRAFT = "draft"
STATUS_PENDING = "pending"
STATUS_PUBLISHED = "published"
STATUS_CLOSED = "closed"
STATUS_ARCHIVED = "archived"

JD_SOURCE_MANUAL = "manual"
JD_SOURCE_AI = "ai"

WORK_MODES = ("onsite", "hybrid", "remote")
EMPLOYMENT_TYPES = ("fulltime", "intern", "parttime")
EDUCATION_LEVELS = ("college", "bachelor", "master", "phd")


class Job(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """招聘职位，整条招聘业务链路的起点；对应文档 §3.2.2 job表"""

    __tablename__ = "job"
    __table_args__ = (
        # 职位列表查询索引：按公司、状态、更新时间筛选排序
        Index("ix_job_company_status_update", "company_id", "status", "update_time"),
        # 职位名称检索索引
        Index("ix_job_title", "title"),
        # 发布时间筛选索引，用于投递页、在招职位列表
        Index("ix_job_published_at", "published_at"),
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="职位名称")
    department: Mapped[str | None] = mapped_column(String(100), index=True, comment="所属部门")
    location: Mapped[str | None] = mapped_column(String(100), comment="工作地点")
    work_mode: Mapped[str | None] = mapped_column(String(20), comment="工作模式：onsite线下 / hybrid混合 / remote远程")
    employment_type: Mapped[str] = mapped_column(String(20), default="fulltime", nullable=False,
                                                  comment="雇佣类型：fulltime全职 / intern实习 / parttime兼职")
    headcount: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="招聘人数")

    description: Mapped[str | None] = mapped_column(Text, comment="职位描述，工作职责内容")
    requirements: Mapped[str | None] = mapped_column(Text, comment="任职要求")
    skills: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False,
                                              comment="技能要求，存储归一后的skill_id数组，用于人岗匹配计算")
    must_have_skills: Mapped[list[int]] = mapped_column(JSON, default=list, nullable=False,
                                                        comment="必备技能skill_id数组，缺失会对匹配分数重罚，和加分技能区分开")

    min_years: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), comment="最低工作经验要求（单位：年）")
    education_level: Mapped[str | None] = mapped_column(String(20),
                                                         comment="最低学历：college大专 / bachelor本科 / master硕士 / phd博士")
    salary_min: Mapped[int | None] = mapped_column(Integer, comment="月薪薪资下限，单位K/月")
    salary_max: Mapped[int | None] = mapped_column(Integer, comment="月薪薪资上限，单位K/月")

    status: Mapped[str] = mapped_column(
        String(20), default=STATUS_DRAFT, nullable=False, index=True,
        comment="职位状态：draft草稿 / pending待审批 / published招聘中 / closed已关闭 / archived已归档"
    )
    jd_source: Mapped[str] = mapped_column(String(20), default=JD_SOURCE_MANUAL, nullable=False,
                                           comment="JD来源：manual人工手写 / ai AI生成后人工修改")
    jd_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False,
                                            comment="JD版本号，JD实质修改版本+1；作为匹配缓存指纹的一部分，版本变动需要重新计算人岗匹配")
    published_at: Mapped[datetime | None] = mapped_column(DateTime, comment="职位正式发布时间")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="职位关闭时间")

    approved_by: Mapped[int | None] = mapped_column(BigInteger, comment="审批人user_id，用人经理")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, comment="审批通过时间")
    reject_reason: Mapped[str | None] = mapped_column(Text, comment="审批驳回原因，审批拒绝时填写")

    apply_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False,
                                             comment="应聘人数冗余计数；列表页直接读取，避免实时count聚合查询")
    created_by: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="职位创建人user_id")
