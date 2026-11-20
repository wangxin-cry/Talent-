"""
安全模块（骨架）

阶段二会补齐：注册/登录、三角色 RBAC、刷新令牌、登录锁定。
现在先提供：密码哈希、JWT 签发与解析、Fernet 加解密（PII / API Key）。
"""
from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------- 密码
def hash_password(plain: str) -> str:
    """bcrypt 哈希密码（数据库只存哈希）"""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码"""
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------- JWT
def create_access_token(
    subject: str | int, role: str, expires_minutes: int | None = None, token_version: int = 0
) -> str:
    """签发 access token（sub 必须是字符串）"""
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "ver": token_version,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str | int, token_version: int = 0) -> str:
    """签发 refresh token"""
    expire = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": str(subject),
        "ver": token_version,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    """解析 JWT，失败返回 None"""
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        logger.debug(f"JWT 解析失败: {exc}")
        return None


# ---------------------------------------------------------------- PII 加密
def _fernet() -> Fernet:
    """生成 Fernet 实例：优先用独立密钥，否则从 SECRET_KEY 派生"""
    raw = settings.CONFIG_SECRET or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt_pii(plain: str | None) -> str | None:
    """加密手机号/邮箱等 PII"""
    if plain is None:
        return None
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_pii(cipher: str | None) -> str | None:
    """解密 PII（无权限的路径不要调用）"""
    if cipher is None:
        return None
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except InvalidToken:
        logger.error("PII 解密失败：密钥不匹配")
        return None


def sha256_hex(value: str) -> str:
    """不可逆哈希：用于去重键、内容指纹"""
    return hashlib.sha256(value.encode()).hexdigest()


def normalize_phone(phone: str | None) -> str | None:
    """手机号归一：去空格/横线/+86"""
    if not phone:
        return None
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits or None
