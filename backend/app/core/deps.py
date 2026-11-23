"""
FastAPI 依赖

提供：
- get_current_payload：解析 JWT
- get_current_user：查库拿 User（状态 + 令牌版本校验）
- require_roles：基于数据库中的 user.role 做三角色权限校验
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.core.tenant import set_company_id
from app.models.company import STATUS_ACTIVE as COMPANY_ACTIVE, Company
from app.models.user import (
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_RECRUITER,
    ROLE_SUPERADMIN,
    STATUS_ACTIVE,
    User,
)
from app.services import api_keys as api_key_service

VALID_ROLES = (ROLE_RECRUITER, ROLE_MANAGER, ROLE_ADMIN, ROLE_SUPERADMIN)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_payload(
    authorization: str | None = Header(default=None, description="Bearer <token>"),
) -> dict:
    """解析 Bearer Token，返回 JWT payload（仅结构校验，不查库）"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供认证信息",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload


async def get_current_user(
    db: DbSession,
    authorization: str | None = Header(default=None, description="Bearer <token>"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key", description="API Key"),
) -> User:
    """
    认证当前用户，支持两种凭证：

    - Authorization: Bearer <JWT>
    - X-API-Key: tm_xxx（长期凭证，供脚本/外部系统调用）

    JWT 同时校验令牌版本：登出 / 改密 / 禁用后旧 token 立即失效。
    """
    if authorization:
        if not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="认证格式错误，应为 Bearer <token>",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_token(token)
        if payload is None or payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录已失效，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            user_id = int(payload["sub"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录已失效，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = await db.get(User, user_id)
        if user is None or user.status != STATUS_ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录已失效，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if int(payload.get("ver", 0)) != user.token_version:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="登录已失效，请重新登录",
                headers={"WWW-Authenticate": "Bearer"},
            )
        await _bind_company(db, user)
        return user

    if x_api_key:
        user = await api_key_service.authenticate(db, x_api_key.strip())
        if user is not None:
            await _bind_company(db, user)
            return user
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效、已过期或已吊销",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="未提供认证信息",
        headers={"WWW-Authenticate": "Bearer"},
    )


# 常用类型别名
CurrentUser = Annotated[User, Depends(get_current_user)]


async def _bind_company(db: AsyncSession, user: User) -> None:
    """把当前用户公司写入请求上下文，并拦截已停用公司的成员"""
    if user.company_id is None:
        set_company_id(None)
        return
    company = await db.get(Company, user.company_id)
    if company is None or company.status != COMPANY_ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="所属公司已停用，请联系平台管理员"
        )
    set_company_id(user.company_id)


async def require_superadmin(user: User = Depends(get_current_user)) -> User:
    """平台超管专用依赖"""
    if user.role != ROLE_SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅平台超级管理员可访问"
        )
    return user


SuperAdmin = Annotated[User, Depends(require_superadmin)]


def require_roles(*roles: str):
    """
    角色校验依赖工厂

    角色以数据库为准（不信任 token 里的 role），
    因此管理员改角色 / 禁用账号后立即生效。

    用法：
        @router.get("/admin/users", dependencies=[Depends(require_roles(ROLE_ADMIN))])
    """

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"当前角色（{user.role}）无权访问该资源",
            )
        return user

    return _checker


# 常用组合
require_admin = require_roles(ROLE_ADMIN)
require_admin_or_manager = require_roles(ROLE_ADMIN, ROLE_MANAGER)
