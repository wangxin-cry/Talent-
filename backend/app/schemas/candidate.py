"""候选人 / 简历相关请求与响应模型"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ResumeFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    original_name: str
    ext: str | None = None
    mime: str | None = None
    size_bytes: int
    sha256: str
    status: str
    parser: str | None = None
    error_reason: str | None = None
    retry_count: int = 0
    parsed_time: datetime | None = None
    create_time: datetime


class CandidateOut(BaseModel):
    id: int
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    city: str | None = None
    education_level: str | None = None
    school: str | None = None
    major: str | None = None
    years_experience: float | None = None
    current_company: str | None = None
    current_title: str | None = None
    skills: list[str] = []
    file_count: int = 0
    latest_status: str | None = None
    create_time: datetime
    update_time: datetime


class CandidateDetailOut(CandidateOut):
    files: list[ResumeFileOut] = []
    resume_id: int | None = None
    structured: dict | None = None
    field_confidence: dict[str, float] = {}
    plain_text: str | None = None
    parser_meta: dict = {}


class CandidateCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=100)
    education_level: str | None = Field(default=None, max_length=20)
    school: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=100)
    years_experience: float | None = Field(default=None, ge=0, le=50)
    current_company: str | None = Field(default=None, max_length=100)
    current_title: str | None = Field(default=None, max_length=100)
    skills: list[str] = []

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("姓名不能为空")
        return value


class CandidateUpdateIn(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=100)
    education_level: str | None = Field(default=None, max_length=20)
    school: str | None = Field(default=None, max_length=100)
    major: str | None = Field(default=None, max_length=100)
    years_experience: float | None = Field(default=None, ge=0, le=50)
    current_company: str | None = Field(default=None, max_length=100)
    current_title: str | None = Field(default=None, max_length=100)
    skills: list[str] | None = None


class CandidateListOut(BaseModel):
    items: list[CandidateOut]
    total: int


class UploadItemOut(BaseModel):
    file_id: int | None = None
    original_name: str
    size_bytes: int
    sha256: str | None = None
    reused: bool = False
    status: str
    candidate_id: int | None = None
    message: str | None = None


class UploadOut(BaseModel):
    items: list[UploadItemOut]


class FileStatusOut(BaseModel):
    id: int
    status: str
    error_reason: str | None = None
    candidate_id: int | None = None


class FileStatusListOut(BaseModel):
    items: list[FileStatusOut]


class DownloadOut(BaseModel):
    url: str
    expires_in: int
    filename: str
