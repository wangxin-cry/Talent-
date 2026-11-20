"""
认证路由

前缀：/api/v1/auth
- 注册 / 登录 / 刷新令牌 / 当前用户
- 邮箱验证 / 重发验证
- 找回密码 / 重置密码
"""
from __future__ import annotations

from fastapi import APIRouter, status

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.schemas.auth import (
    AccessTokenOut,
    ForgotPasswordIn,
    LoginIn,
    MessageOut,
    RefreshIn,
    RegisterIn,
    RegisterOut,
    ResendVerificationIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
    VerifyEmailIn,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post(
    "/register",
    response_model=RegisterOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册（默认 recruiter）",
)
async def register(payload: RegisterIn, db: DbSession) -> RegisterOut:
    user = await auth_service.register_user(db, payload)
    email_sent = settings.email_enabled
    message = (
        "注册成功，验证邮件已发送，请查收邮件并完成验证后登录"
        if email_sent
        else "注册成功，验证链接已输出到后端控制台，请完成验证后登录"
    )
    return RegisterOut(
        user=UserOut.model_validate(user),
        email_sent=email_sent,
        message=message,
    )


@router.post("/login", response_model=TokenOut, summary="登录")
async def login(payload: LoginIn, db: DbSession) -> TokenOut:
    user = await auth_service.authenticate(db, payload.account, payload.password)
    access_token, refresh_token = auth_service.build_token_pair(user)
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut.model_validate(user),
    )


@router.post("/refresh", response_model=AccessTokenOut, summary="刷新 access token")
async def refresh(payload: RefreshIn, db: DbSession) -> AccessTokenOut:
    _, access_token = await auth_service.refresh_access_token(db, payload.refresh_token)
    return AccessTokenOut(
        access_token=access_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", response_model=MessageOut, summary="登出")
async def logout(current_user: CurrentUser, db: DbSession) -> MessageOut:
    await auth_service.logout(db, current_user)
    return MessageOut(message="已退出登录")


@router.get("/me", response_model=UserOut, summary="当前用户")
async def me(current_user: CurrentUser) -> UserOut:
    return UserOut.model_validate(current_user)


@router.post("/verify-email", response_model=MessageOut, summary="验证邮箱")
async def verify_email(payload: VerifyEmailIn, db: DbSession) -> MessageOut:
    await auth_service.verify_email(db, payload.token)
    return MessageOut(message="邮箱验证成功，请登录")


@router.post("/resend-verification", response_model=MessageOut, summary="重发验证邮件")
async def resend_verification(payload: ResendVerificationIn, db: DbSession) -> MessageOut:
    message = await auth_service.resend_verification(db, payload.email)
    return MessageOut(message=message)


@router.post("/forgot-password", response_model=MessageOut, summary="找回密码")
async def forgot_password(payload: ForgotPasswordIn, db: DbSession) -> MessageOut:
    message = await auth_service.request_password_reset(db, payload.email)
    return MessageOut(message=message)


@router.post("/reset-password", response_model=MessageOut, summary="重置密码")
async def reset_password(payload: ResetPasswordIn, db: DbSession) -> MessageOut:
    await auth_service.reset_password(db, payload.token, payload.new_password)
    return MessageOut(message="密码已重置，请使用新密码登录")
