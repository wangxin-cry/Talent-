"""
候选人 / 简历文件 / 简历解析结果（阶段四）

三张表分工：
- candidate：人。同一人多份简历只建一条，dedupe_key 唯一约束兜底
- resume_file：原始文件元信息；文件本体在 MinIO，库里只存 bucket + object_key
- resume：每次解析产出的结构化结果 + 字段置信度（reparse 生成新版本）
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import CompanyScopedMixin, IdMixin, TimestampMixin

# resume_file.status
RF_PENDING = "pending"
RF_PARSING = "parsing"
RF_SUCCESS = "success"
RF_FAILED = "failed"

FILE_STATUS_LABELS = {
    RF_PENDING: "待解析",
    RF_PARSING: "解析中",
    RF_SUCCESS: "已解析",
    RF_FAILED: "解析失败",
}


class Candidate(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """候选人档案：同一个人多份简历合并为一条"""

    __tablename__ = "candidate"
    __table_args__ = (
        # 同一公司下判重键唯一：并发上传同一人时由数据库拦住
        UniqueConstraint("company_id", "dedupe_key", name="uq_candidate_company_dedupe"),
    )

    name: Mapped[str | None] = mapped_column(String(100), index=True, comment="姓名")
    phone_enc: Mapped[str | None] = mapped_column(String(500), comment="手机号密文（Fernet）")
    phone_hash: Mapped[str | None] = mapped_column(String(64), index=True,
                                                   comment="手机号不可逆哈希，用于去重与精确查找")
    email_enc: Mapped[str | None] = mapped_column(String(500), comment="邮箱密文")
    email_hash: Mapped[str | None] = mapped_column(String(64), index=True,
                                                    comment="邮箱不可逆哈希")

    dedupe_key: Mapped[str] = mapped_column(
        String(120), nullable=False,
        comment="判重键：phone:<hash> / email:<hash> / file:<sha256> / manual:<id>"
    )

    city: Mapped[str | None] = mapped_column(String(100), comment="所在城市")
    education_level: Mapped[str | None] = mapped_column(String(20),
                                                         comment="最高学历：college/bachelor/master/phd，未知时存原文")
    school: Mapped[str | None] = mapped_column(String(100), comment="最高学历院校")
    major: Mapped[str | None] = mapped_column(String(100), comment="专业")
    years_experience: Mapped[Decimal | None] = mapped_column(Numeric(4, 1), comment="工作年限（年）")
    current_company: Mapped[str | None] = mapped_column(String(100), comment="当前/最近公司")
    current_title: Mapped[str | None] = mapped_column(String(100), comment="当前/最近职位")

    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False,
                                              comment="技能名数组（归一后的字符串）")
    resume_text: Mapped[str | None] = mapped_column(Text, comment="最新一份简历纯文本，供匹配/full-text 使用")

    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False,
                                             comment="逻辑删除标记")
    created_by: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="创建人 user_id")


class ResumeFile(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """简历原始文件元信息（文件本体不在数据库）"""

    __tablename__ = "resume_file"
    __table_args__ = (
        # 同一公司内文件内容唯一：重复上传直接复用，不再解析；
        # 不同公司可各自收录同一份简历
        UniqueConstraint("company_id", "sha256", name="uq_resume_file_company_sha"),
    )

    candidate_id: Mapped[int | None] = mapped_column(BigInteger, index=True,
                                                      comment="解析成功后归属的候选人 id")
    bucket: Mapped[str] = mapped_column(String(100), default="", nullable=False, comment="MinIO 桶名")
    object_key: Mapped[str] = mapped_column(String(500), nullable=False, comment="对象键，不含 PII")
    etag: Mapped[str | None] = mapped_column(String(100), comment="对象存储返回的 etag")
    original_name: Mapped[str] = mapped_column(String(255), default="", nullable=False, comment="原始文件名")
    ext: Mapped[str] = mapped_column(String(20), default="", nullable=False, comment="扩展名（小写，带点）")
    mime: Mapped[str | None] = mapped_column(String(100), comment="MIME 类型")
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False, comment="文件字节数")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="文件内容 sha256")

    source: Mapped[str] = mapped_column(String(20), default="upload", nullable=False,
                                         comment="来源：upload / email / api")
    applied_job_id: Mapped[int | None] = mapped_column(BigInteger, index=True,
                                                        comment="上传时选择的应聘职位（可选）")

    status: Mapped[str] = mapped_column(String(20), default=RF_PENDING, nullable=False, index=True,
                                         comment="pending待解析 / parsing解析中 / success成功 / failed失败")
    parser: Mapped[str | None] = mapped_column(String(50), comment="解析器：pdfplumber/pymupdf/python-docx/vision/pdf+vision")
    error_reason: Mapped[str | None] = mapped_column(Text, comment="失败原因，可直接展示给用户")
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="重新解析次数")
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, index=True, comment="上传人 user_id")
    parsed_time: Mapped[datetime | None] = mapped_column(DateTime, comment="解析完成时间")


class Resume(IdMixin, TimestampMixin, CompanyScopedMixin, Base):
    """简历解析结果：一份文件可多次解析，每次一个版本"""

    __tablename__ = "resume"

    candidate_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="候选人 id")
    file_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="来源文件 id")
    structured: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False,
                                              comment="结构化字段：basic/education/work/projects/skills/certificates")
    field_confidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False,
                                                    comment="字段置信度 0~1，前端低置信标黄")
    plain_text: Mapped[str | None] = mapped_column(Text, comment="解析出的纯文本（截断 20 万字）")
    parser_meta: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False,
                                               comment="解析元信息：引擎、页数、模型、token、是否降级")
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, comment="文本内容指纹")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False,
                                              comment="是否该候选人当前主简历")
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="解析版本号")
