"""系统配置业务逻辑"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant import get_company_id
from app.models.system_config import SystemConfig

# 默认配置：表里没有记录时展示这些值
DEFAULT_CONFIGS: dict[str, tuple[Any, str]] = {
    "ai.default_use_llm": (True, "对话与 Agent 默认调用 LLM"),
    "resume.max_upload_mb": (20, "单个简历文件大小上限（MB）"),
    "matching.default_top_n": (3, "一键评估默认取前 N 名"),
    "notification.email_enabled": (False, "是否启用邮件通知"),
    "security.api_key_enabled": (True, "是否允许 API Key 访问"),
}


def _validate(key: str, value: Any) -> Any:
    if key == "ai.default_use_llm" and not isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该配置必须是布尔值")
    if key == "resume.max_upload_mb":
        if not isinstance(value, int) or not 1 <= value <= 100:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="上传大小需在 1~100 MB")
    if key == "matching.default_top_n":
        if not isinstance(value, int) or not 1 <= value <= 20:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="top_n 需在 1~20")
    if key.startswith("notification.") and not isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="通知开关必须是布尔值")
    if key.startswith("security.") and not isinstance(value, bool):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="安全开关必须是布尔值")
    return value


async def list_configs(db: AsyncSession) -> list[dict]:
    company_id = get_company_id()
    query = select(SystemConfig)
    if company_id is not None:
        query = query.where(SystemConfig.company_id == company_id)
    rows = (await db.execute(query)).scalars().all()
    stored = {row.key: row for row in rows}
    items: list[dict] = []
    for key, (value, description) in DEFAULT_CONFIGS.items():
        row = stored.pop(key, None)
        items.append(
            {
                "key": key,
                "value": row.value if row else value,
                "description": row.description if row and row.description else description,
                "updated_by": row.updated_by if row else None,
                "update_time": row.update_time if row else None,
            }
        )
    for key, row in stored.items():
        items.append(
            {
                "key": key,
                "value": row.value,
                "description": row.description,
                "updated_by": row.updated_by,
                "update_time": row.update_time,
            }
        )
    return items


async def get_value(db: AsyncSession, key: str) -> Any:
    company_id = get_company_id()
    query = select(SystemConfig).where(SystemConfig.key == key)
    if company_id is not None:
        query = query.where(SystemConfig.company_id == company_id)
    row = (await db.execute(query)).scalars().first()
    if row is not None:
        return row.value
    return DEFAULT_CONFIGS.get(key, (None, ""))[0]


async def upsert_config(
    db: AsyncSession, key: str, value: Any, description: str | None, user_id: int
) -> SystemConfig:
    key = key.strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="配置键不能为空")
    value = _validate(key, value)
    company_id = get_company_id()
    conditions = [SystemConfig.key == key]
    if company_id is not None:
        conditions.append(SystemConfig.company_id == company_id)
    row = (await db.execute(select(SystemConfig).where(*conditions))).scalar_one_or_none()
    if row is None:
        row = SystemConfig(
            company_id=company_id or 1,
            key=key,
            value=value,
            description=description,
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.value = value
        if description is not None:
            row.description = description
        row.updated_by = user_id
    await db.flush()
    return row
