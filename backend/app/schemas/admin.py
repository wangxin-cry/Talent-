"""管理员 / 系统配置 / API Key / 审计相关 schema"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    department: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    status: str
    email_verified: bool
    last_login_at: datetime | None = None
    locked_until: datetime | None = None
    create_time: datetime


class AdminUserUpdateIn(BaseModel):
    role: Literal["recruiter", "manager", "admin"] | None = None
    status: Literal["active", "disabled"] | None = None
    department: str | None = Field(default=None, max_length=100)


class SystemConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    value: Any
    description: str | None = None
    updated_by: int | None = None
    update_time: datetime | None = None


class SystemConfigUpdateIn(BaseModel):
    value: Any
    description: str | None = Field(default=None, max_length=255)


class AuditLogOut(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: int | None = None
    detail: dict = Field(default_factory=dict)
    user_id: int | None = None
    user_name: str | None = None
    create_time: datetime


class AuditLogListOut(BaseModel):
    items: list[AuditLogOut]
    total: int


class ApiKeyCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    expires_in_days: int | None = Field(default=None, ge=1, le=3650)


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    create_time: datetime
    status: str = "active"


class ApiKeyCreatedOut(ApiKeyOut):
    key: str = Field(description="明文密钥，仅创建时返回一次")


class ApiKeyListOut(BaseModel):
    items: list[ApiKeyOut]


class AdminApiKeyOut(ApiKeyOut):
    user_id: int
    user_name: str | None = None


class AdminApiKeyListOut(BaseModel):
    items: list[AdminApiKeyOut]
