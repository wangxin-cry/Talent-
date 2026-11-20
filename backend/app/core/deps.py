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
from app.models.user import ROLE_ADMIN, ROLE_MANAGER, ROLE_RECRUITER, STATUS_ACTIVE, User

VALID_ROLES = (ROLE_RECRUITER, ROLE_MANAGER, ROLE_ADMIN)

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


async def get_current_user(db: DbSession, payload: dict = Depends(get_current_payload)) -> User:
    """
    解析 Bearer Token 并查库，返回有效用户

    同时校验令牌版本：登出 / 改密后旧 token 立即失效。
    """
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

    return user


# 常用类型别名
CurrentUser = Annotated[User, Depends(get_current_user)]


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
