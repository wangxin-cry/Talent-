"""
认证业务逻辑

覆盖：注册、登录（失败锁定）、令牌刷新、邮箱验证、找回密码。

约定：
- 时间统一用 models.base.utcnow()（naive UTC），与数据库 DateTime 字段一致
- 登录失败不区分"用户不存在"和"密码错误"，防止账号枚举
- 邮箱验证 / 密码重置均为一次性 token，库里只存 hash
"""
from __future__ import annotations

import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    sha256_hex,
    verify_password,
)
from app.models.auth_token import PURPOSE_RESET_PASSWORD, PURPOSE_VERIFY_EMAIL, AuthToken
from app.models.base import utcnow
from app.models.user import ROLE_RECRUITER, STATUS_ACTIVE, User
from app.schemas.auth import RegisterIn
from app.services.email import send_reset_password_email, send_verification_email

MAX_LOGIN_FAILS = 5
LOCK_MINUTES = 15

FORGOT_PASSWORD_MESSAGE = "如果该邮箱已注册，重置链接已发送，请查收邮件"
RESEND_VERIFY_MESSAGE = "如果该邮箱已注册且未验证，验证邮件已发送，请查收邮件"


# ---------------------------------------------------------------- 查询
async def _get_user_by_account(db: AsyncSession, account: str) -> User | None:
    """按用户名或邮箱查用户（邮箱不区分大小写）"""
    account = account.strip()
    result = await db.execute(
        select(User).where(or_(User.name == account, User.email == account.lower()))
    )
    return result.scalar_one_or_none()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.strip().lower()))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------- 注册
async def register_user(db: AsyncSession, data: RegisterIn) -> User:
    """
    注册用户

    角色固定 recruiter（manager / admin 由管理员后续创建）。
    注册后一律处于"邮箱未验证"，必须先完成验证才能登录；
    开发模式（未配置 SMTP）会把验证链接打印到后端控制台。
    """
    email = data.email.strip().lower()

    exists = await db.execute(
        select(User.id).where(or_(User.name == data.name, User.email == email))
    )
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名或邮箱已被注册")

    user = User(
        name=data.name,
        email=email,
        password=hash_password(data.password),
        role=ROLE_RECRUITER,
        status=STATUS_ACTIVE,
    )

    db.add(user)
    await db.commit()
    await db.refresh(user)

    await send_verification(db, user)
    return user


# ---------------------------------------------------------------- 登录
async def authenticate(db: AsyncSession, account: str, password: str) -> User:
    """校验账号密码；处理失败计数与锁定，未验证邮箱拒绝登录"""
    user = await _get_user_by_account(db, account)
    now = utcnow()

    if user is None or not verify_password(password, user.password):
        if user is not None:
            user.login_fail_count += 1
            if user.login_fail_count >= MAX_LOGIN_FAILS:
                user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
                user.login_fail_count = 0
                logger.warning(f"账号 {user.name} 连续登录失败，锁定 {LOCK_MINUTES} 分钟")
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    if user.locked_until is not None and user.locked_until > now:
        remaining = int((user.locked_until - now).total_seconds() // 60) + 1
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号已锁定，请 {remaining} 分钟后再试",
        )

    if user.status != STATUS_ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

    if user.email_verified_at is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邮箱未验证，请先完成邮箱验证",
        )

    user.login_fail_count = 0
    user.locked_until = None
    user.last_login_at = now
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------- 令牌
def build_token_pair(user: User) -> tuple[str, str]:
    """签发 access + refresh（带令牌版本）"""
    return (
        create_access_token(user.id, user.role, token_version=user.token_version),
        create_refresh_token(user.id, token_version=user.token_version),
    )


def _check_token_version(payload: dict, user: User) -> None:
    """令牌版本不一致说明已登出 / 改密，旧 token 作废"""
    if int(payload.get("ver", 0)) != user.token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )


async def refresh_access_token(db: AsyncSession, refresh_token: str) -> tuple[User, str]:
    """用 refresh token 换新的 access token"""
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )

    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )

    user = await db.get(User, user_id)
    if user is None or user.status != STATUS_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录"
        )
    _check_token_version(payload, user)
    return user, create_access_token(user.id, user.role, token_version=user.token_version)


async def logout(db: AsyncSession, user: User) -> None:
    """登出：令牌版本 +1，该用户已签发的 access / refresh 全部失效"""
    user.token_version += 1
    await db.commit()


# ---------------------------------------------------------------- 邮箱验证
async def _issue_token(db: AsyncSession, user: User, purpose: str, minutes: int) -> str:
    """签发一次性 token，并把旧的未用 token 作废"""
    raw = secrets.token_urlsafe(32)

    await db.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.purpose == purpose,
            AuthToken.used_at.is_(None),
        )
        .values(used_at=utcnow())
    )
    db.add(
        AuthToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=sha256_hex(raw),
            expires_at=utcnow() + timedelta(minutes=minutes),
        )
    )
    await db.commit()
    return raw


async def _consume_token(db: AsyncSession, raw: str, purpose: str) -> tuple[User, AuthToken]:
    """校验并消费 token"""
    result = await db.execute(
        select(AuthToken).where(
            AuthToken.token_hash == sha256_hex(raw), AuthToken.purpose == purpose
        )
    )
    token = result.scalar_one_or_none()
    if token is None or token.used_at is not None or token.expires_at <= utcnow():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="链接无效或已过期，请重新获取"
        )

    user = await db.get(User, token.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="链接对应的账号不存在")

    token.used_at = utcnow()
    await db.flush()
    return user, token


async def send_verification(db: AsyncSession, user: User) -> None:
    """生成验证链接并发送；开发模式写日志"""
    if user.email_verified_at is not None:
        return

    raw = await _issue_token(
        db, user, PURPOSE_VERIFY_EMAIL, settings.EMAIL_VERIFY_EXPIRE_HOURS * 60
    )
    link = f"{settings.FRONTEND_BASE_URL}/verify-email?token={raw}"

    if not settings.email_enabled:
        # 开发模式：不发信，把链接直接打到控制台，方便本地验证
        logger.warning(f"[DEV] 邮件未启用，邮箱验证链接（{user.email}）：{link}")
        print(f"\n[DEV] 邮箱验证链接（{user.email}）：\n[DEV] {link}\n", flush=True)
        return
    await send_verification_email(user.email, user.name, link)


async def verify_email(db: AsyncSession, raw_token: str) -> None:
    """校验 token 并标记邮箱已验证"""
    user, _ = await _consume_token(db, raw_token, PURPOSE_VERIFY_EMAIL)
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    await db.commit()


async def resend_verification(db: AsyncSession, email: str) -> str:
    """重发验证邮件（开发模式打印验证链接到控制台）"""
    user = await get_user_by_email(db, email)

    if user is not None and user.email_verified_at is None:
        await send_verification(db, user)

    return RESEND_VERIFY_MESSAGE


# ---------------------------------------------------------------- 找回密码
async def request_password_reset(db: AsyncSession, email: str) -> str:
    """发送重置链接；无论邮箱是否存在都返回同一句话"""
    user = await get_user_by_email(db, email)
    if user is None:
        return FORGOT_PASSWORD_MESSAGE

    raw = await _issue_token(
        db, user, PURPOSE_RESET_PASSWORD, settings.RESET_TOKEN_EXPIRE_MINUTES
    )
    link = f"{settings.FRONTEND_BASE_URL}/reset-password?token={raw}"

    if settings.email_enabled:
        await send_reset_password_email(user.email, user.name, link)
    else:
        logger.warning(f"[DEV] 邮件未启用，密码重置链接（{user.email}）：{link}")

    return FORGOT_PASSWORD_MESSAGE


async def reset_password(db: AsyncSession, raw_token: str, new_password: str) -> None:
    """
    重置密码

    能拿到邮件里的 token 即证明邮箱归属，因此顺带把未验证的邮箱标记为已验证。
    """
    user, _ = await _consume_token(db, raw_token, PURPOSE_RESET_PASSWORD)
    user.password = hash_password(new_password)
    user.login_fail_count = 0
    user.locked_until = None
    # 密码已变更，作废此前签发的所有令牌
    user.token_version += 1
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    await db.commit()
    logger.info(f"用户 {user.name} 已重置密码")
