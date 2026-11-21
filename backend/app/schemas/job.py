"""
职位 / 技能相关请求与响应模型
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.job import (
    EDUCATION_LEVELS,
    EMPLOYMENT_TYPES,
    WORK_MODES,
)


# ---------------------------------------------------------------- 技能
class SkillBrief(BaseModel):
    """技能简要信息（职位 / JD 返回用）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    display_name: str | None = None


class SkillOut(SkillBrief):
    aliases: list[str] = []
    category: str | None = None
    is_active: bool = True


class SkillCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    display_name: str | None = Field(default=None, max_length=100)
    aliases: list[str] = []
    category: str | None = Field(default=None, max_length=50)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("技能名不能为空")
        return value


# ---------------------------------------------------------------- 职位
class JobCreateIn(BaseModel):
    """创建职位（一律落为 draft）"""

    title: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    work_mode: str | None = None
    employment_type: str = "fulltime"
    headcount: int = Field(default=1, ge=1, le=999)
    description: str | None = None
    requirements: str | None = None
    skills: list[int] = []
    must_have_skills: list[int] = []
    min_years: float | None = Field(default=None, ge=0, le=50)
    education_level: str | None = None
    salary_min: int | None = Field(default=None, ge=0, le=1000)
    salary_max: int | None = Field(default=None, ge=0, le=1000)
    jd_source: str = "manual"

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("职位名称不能为空")
        return value

    @field_validator("work_mode")
    @classmethod
    def _check_work_mode(cls, value: str | None) -> str | None:
        if value and value not in WORK_MODES:
            raise ValueError(f"work_mode 只能是 {WORK_MODES}")
        return value

    @field_validator("employment_type")
    @classmethod
    def _check_employment_type(cls, value: str) -> str:
        if value not in EMPLOYMENT_TYPES:
            raise ValueError(f"employment_type 只能是 {EMPLOYMENT_TYPES}")
        return value

    @field_validator("education_level")
    @classmethod
    def _check_education(cls, value: str | None) -> str | None:
        if value and value not in EDUCATION_LEVELS:
            raise ValueError(f"education_level 只能是 {EDUCATION_LEVELS}")
        return value

    @model_validator(mode="after")
    def _check_salary(self) -> "JobCreateIn":
        if (
            self.salary_min is not None
            and self.salary_max is not None
            and self.salary_min > self.salary_max
        ):
            raise ValueError("薪资下限不能大于上限")
        self.skills = list(dict.fromkeys(self.skills))
        self.must_have_skills = list(dict.fromkeys(self.must_have_skills))
        return self


class JobUpdateIn(BaseModel):
    """编辑职位（字段可选；实质改动会递增 jd_version）"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    work_mode: str | None = None
    employment_type: str | None = None
    headcount: int | None = Field(default=None, ge=1, le=999)
    description: str | None = None
    requirements: str | None = None
    skills: list[int] | None = None
    must_have_skills: list[int] | None = None
    min_years: float | None = Field(default=None, ge=0, le=50)
    education_level: str | None = None
    salary_min: int | None = Field(default=None, ge=0, le=1000)
    salary_max: int | None = Field(default=None, ge=0, le=1000)

    @field_validator("work_mode")
    @classmethod
    def _check_work_mode(cls, value: str | None) -> str | None:
        if value and value not in WORK_MODES:
            raise ValueError(f"work_mode 只能是 {WORK_MODES}")
        return value

    @field_validator("employment_type")
    @classmethod
    def _check_employment_type(cls, value: str | None) -> str | None:
        if value and value not in EMPLOYMENT_TYPES:
            raise ValueError(f"employment_type 只能是 {EMPLOYMENT_TYPES}")
        return value

    @field_validator("education_level")
    @classmethod
    def _check_education(cls, value: str | None) -> str | None:
        if value and value not in EDUCATION_LEVELS:
            raise ValueError(f"education_level 只能是 {EDUCATION_LEVELS}")
        return value

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("职位名称不能为空")
        return value

    @model_validator(mode="after")
    def _dedupe_skills(self) -> "JobUpdateIn":
        if self.skills is not None:
            self.skills = list(dict.fromkeys(self.skills))
        if self.must_have_skills is not None:
            self.must_have_skills = list(dict.fromkeys(self.must_have_skills))
        return self


class JobOut(BaseModel):
    """职位详情 / 列表项"""

    id: int
    title: str
    department: str | None = None
    location: str | None = None
    work_mode: str | None = None
    employment_type: str
    headcount: int
    description: str | None = None
    requirements: str | None = None
    skills: list[SkillBrief] = []
    must_have_skills: list[SkillBrief] = []
    min_years: float | None = None
    education_level: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    status: str
    jd_source: str
    jd_version: int
    published_at: datetime | None = None
    closed_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    reject_reason: str | None = None
    apply_count: int
    created_by: int | None = None
    create_time: datetime
    update_time: datetime


class JobListOut(BaseModel):
    items: list[JobOut]
    total: int


# ---------------------------------------------------------------- AI 生成 JD
class JDGenerateIn(BaseModel):
    """AI 生成 JD 的输入"""

    title: str = Field(min_length=1, max_length=200)
    department: str | None = Field(default=None, max_length=100)
    location: str | None = Field(default=None, max_length=100)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    level: str | None = Field(default=None, max_length=50)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("职位名称不能为空")
        return value


class JDGenerateOut(BaseModel):
    """生成结果（必须可编辑，不直接落库）"""

    summary: str
    description: str
    requirements: str
    skills: list[SkillBrief] = []
    must_have_skills: list[SkillBrief] = []
    ai_generated: bool
    note: str | None = None

class JobRejectIn(BaseModel):
    """ 驳回职位 """
    reason: str = Field(min_length=1, max_length=100)

    @field_validator("reason")
    @classmethod
    def _clean_reason(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("驳回原因不能为空")
        return value
