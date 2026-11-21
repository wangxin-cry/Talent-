"""
RAG 向量切片元数据（阶段八）

FAISS 只存向量，不存文本；本表保存切片正文、来源与过滤字段。
FAISS 的 int64 id 直接复用本表主键，两者一一对应。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin, utcnow

# doc_type
DOC_RESUME = "resume"
DOC_JOB = "job"
DOC_QUESTION = "question"

DOC_TYPE_LABELS = {
    DOC_RESUME: "简历",
    DOC_JOB: "职位",
    DOC_QUESTION: "面试题",
}


class RagChunk(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """一个可检索的文本切片"""

    __tablename__ = "rag_chunk"
    __table_args__ = (
        UniqueConstraint("chunk_key", name="uq_rag_chunk_key"),
        Index("ix_rag_chunk_scope", "doc_type", "source_id"),
    )

    doc_type: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True,
        comment="resume / job / question",
    )
    source_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True,
        comment="来源主键：candidate_id / job_id / question_id",
    )
    chunk_key: Mapped[str] = mapped_column(
        String(120), nullable=False,
        comment="确定性切片键，用于幂等更新",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="参与向量化的正文")
    chunk_meta: Mapped[dict] = mapped_column(
        JSON, default=dict, nullable=False,
        comment="过滤/展示用元数据：chunk_type、job_id、candidate_id 等",
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="逻辑删除标记",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False, comment="切片最后更新时间",
    )
