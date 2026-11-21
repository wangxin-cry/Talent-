"""人岗匹配结果表（可解释评分 + 命中/缺失明细 + 缓存指纹）"""
from __future__ import annotations

from sqlalchemy import BigInteger, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import IdMixin, TimestampMixin


class MatchResult(IdMixin, TimestampMixin, Base):
    """一次人岗匹配的完整结果，支持缓存复用"""

    __tablename__ = "match_result"
    __table_args__ = (
        Index("ix_match_result_job_id", "job_id"),
        Index("ix_match_result_candidate_id", "candidate_id"),
        Index("ix_match_result_fingerprint", "fingerprint"),
    )

    job_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="职位 id")
    candidate_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="候选人 id")
    resume_id: Mapped[int | None] = mapped_column(BigInteger, comment="参与计算的简历版本 id")

    score: Mapped[float] = mapped_column(Float, nullable=False, comment="综合分 0~100")
    skill_score: Mapped[float | None] = mapped_column(Float, comment="技能得分 0~1")
    exp_score: Mapped[float | None] = mapped_column(Float, comment="经验得分 0~1")
    edu_score: Mapped[float | None] = mapped_column(Float, comment="学历得分 0~1")
    other_score: Mapped[float | None] = mapped_column(Float, comment="其他得分 0~1")

    matched_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False, comment="命中技能名")
    missing_skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False, comment="缺失技能名")

    summary: Mapped[str | None] = mapped_column(Text, comment="一句话结论，列表直接展示")
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False,
                                         comment="完整理由明细（各维度扣分、经验差等）")

    fingerprint: Mapped[str | None] = mapped_column(String(64),
                                                    comment="计算指纹：jd_version + resume content_hash")
    feedback: Mapped[str | None] = mapped_column(String(20), comment="HR 反馈：fit / unfit / null")
