"""公司（租户）相关请求 / 响应模型"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompanyLookupOut(BaseModel):
    """注册时按邀请码回显公司"""

    name: str
    slug: str


class CompanyCurrentOut(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    invite_code: str | None = None
    member_count: int = 0


class CompanyMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    status: str
    create_time: datetime


class CompanyMemberUpdateIn(BaseModel):
    role: Literal["recruiter", "manager", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None


class PlatformCompanyOut(BaseModel):
    id: int
    name: str
    slug: str
    status: str
    invite_code: str
    member_count: int
    create_time: datetime


class PlatformCompanyCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=100)


class PlatformCompanyUpdateIn(BaseModel):
    status: Literal["active", "disabled"]
