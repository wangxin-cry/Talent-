"""
认证相关请求 / 响应模型
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

_PASSWORD_HAS_LETTER = re.compile(r"[A-Za-z]")
_PASSWORD_HAS_DIGIT = re.compile(r"\d")


def _check_password_strength(value: str) -> str:
    """密码策略：8~64 位，同时包含字母和数字"""
    if not _PASSWORD_HAS_LETTER.search(value) or not _PASSWORD_HAS_DIGIT.search(value):
        raise ValueError("密码需同时包含字母和数字")
    return value


class RegisterIn(BaseModel):
    """注册"""

    name: str = Field(min_length=2, max_length=50, description="登录名，唯一")
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)
    mode: Literal["create", "join"] = Field(
        default="join", description="create=新建公司（注册者成为公司管理员）；join=用邀请码加入"
    )
    company_name: str | None = Field(default=None, max_length=100, description="新建公司时的公司名称")
    invite_code: str | None = Field(default=None, max_length=16, description="加入公司时的邀请码")
    role: Literal["recruiter", "manager"] = Field(
        default="recruiter", description="加入公司时的身份；新建公司时固定为公司管理员"
    )

    @model_validator(mode="after")
    def _check_company_info(self):
        if self.mode == "create":
            if not (self.company_name or "").strip():
                raise ValueError("请填写公司名称")
        else:
            if not (self.invite_code or "").strip():
                raise ValueError("请填写公司邀请码")
            self.invite_code = self.invite_code.strip().upper()
        return self

    @field_validator("name")
    @classmethod
    def _check_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("登录名不能为空且不能包含空格")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _check_password_strength(value)


class LoginIn(BaseModel):
    """登录（账号可以是用户名或邮箱）"""

    account: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=64)


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=1)


class ResendVerificationIn(BaseModel):
    email: EmailStr


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _check_password_strength(value)


class UserOut(BaseModel):
    """用户信息（不含密码）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    nickname: str | None = None
    email: str
    role: str
    department: str | None = None
    phone: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    status: str
    email_verified: bool
    last_login_at: datetime | None = None
    create_time: datetime


class ProfileUpdateIn(BaseModel):
    """个人资料：登录名与邮箱不可在这里修改；头像走独立上传接口"""

    nickname: str | None = Field(default=None, max_length=50)
    phone: str | None = Field(default=None, max_length=30)
    bio: str | None = Field(default=None, max_length=255)


class TokenOut(BaseModel):
    """登录 / 注册后的令牌"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="access token 有效期（秒）")
    user: UserOut


class AccessTokenOut(BaseModel):
    """刷新令牌后的新 access token"""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MessageOut(BaseModel):
    message: str


class CancelAccountIn(BaseModel):
    """自助注销账号：需要登录密码二次确认"""

    password: str = Field(min_length=1, max_length=128)


class CancelAccountOut(BaseModel):
    message: str
    deleted_jobs: int
    deleted_candidates: int
    deleted_applications: int
    deleted_files: int


class RegisterOut(BaseModel):
    """注册结果：未验证邮箱时拿不到登录令牌"""

    user: UserOut
    email_sent: bool
    message: str
