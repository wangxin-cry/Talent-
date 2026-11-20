"""
FastAPI 依赖（骨架）

阶段二补齐：
- get_current_user：解析 JWT、查用户
- require_role：三角色权限校验
现在先定义好函数签名与错误约定，业务路由可以直接依赖它们。
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token

# 角色常量（与数据库设计中 user.role 一致）
ROLE_RECRUITER = "recruiter"
ROLE_MANAGER = "manager"
ROLE_ADMIN = "admin"
VALID_ROLES = (ROLE_RECRUITER, ROLE_MANAGER, ROLE_ADMIN)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_payload(
    authorization: str | None = Header(default=None, description="Bearer <token>"),
) -> dict:
    """
    解析 Bearer Token，返回 JWT payload

    骨架阶段只校验 token 结构；阶段二改为查库取 User 对象。
    """
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


def require_roles(*roles: str):
    """
    角色校验依赖工厂

    用法：
        @router.get("/admin/users", dependencies=[Depends(require_roles(ROLE_ADMIN))])
    """

    async def _checker(payload: dict = Depends(get_current_payload)) -> dict:
        role = payload.get("role")
        if role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"当前角色（{role}）无权访问该资源",
            )
        return payload

    return _checker


# 常用组合
require_admin = require_roles(ROLE_ADMIN)
require_admin_or_manager = require_roles(ROLE_ADMIN, ROLE_MANAGER)
