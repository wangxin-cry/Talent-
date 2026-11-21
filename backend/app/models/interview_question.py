"""AI 面试题（阶段六）

按 application 落库，fingerprint 用于缓存：
    sha256(题目版本 + jd_version + 主简历 content_hash + 缺口特征)
指纹不变时重复点击直接读缓存，不再调用 LLM。
"""
from __future__ import annotations

from sqlalchemy import BigInteger, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin


class InterviewQuestion(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """一道面试题及其考察点、引用依据、追问"""

    __tablename__ = "interview_question"
    __table_args__ = (
        Index("ix_interview_question_app_fp", "application_id", "fingerprint"),
    )

    application_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True,
                                                 comment="所属应聘记录")
    job_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="职位 id")
    candidate_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="候选人 id")

    category: Mapped[str] = mapped_column(String(20), default="general", nullable=False,
                                           comment="project/skill/gap/experience/scenario/motivation")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="面试题")
    looking_for: Mapped[str | None] = mapped_column(Text, comment="考察点")
    reference: Mapped[str | None] = mapped_column(Text,
                                                   comment="引用依据：项目/技能/经历/任职/缺口")
    follow_up: Mapped[str | None] = mapped_column(Text, comment="追问")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="展示顺序")
    source: Mapped[str] = mapped_column(String(20), default="template", nullable=False,
                                         comment="llm / llm_rag / template")
    fingerprint: Mapped[str | None] = mapped_column(String(64), comment="生成指纹，用于缓存")
    # 生成时使用的知识库参考来源；同一批题目每行存同一份，
    # 便于页面刷新或命中缓存时仍能展示"参考了哪些相似候选人/历史题"。
    rag_sources: Mapped[list] = mapped_column(
        JSON, default=list, nullable=False, comment="RAG 参考来源列表"
    )
