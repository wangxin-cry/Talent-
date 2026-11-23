"""
请求级公司上下文

用途：让 service 层不必层层透传 company_id。
- 登录接口通过 get_current_user 写入当前用户公司
- 公开接口（招聘页/投递）按职位所属公司显式写入
- Celery 任务在任务开头显式写入
"""
from __future__ import annotations

from contextvars import ContextVar

_company_id: ContextVar[int | None] = ContextVar("talentmatch_company_id", default=None)


def set_company_id(company_id: int | None) -> None:
    _company_id.set(company_id)


def reset_company_id() -> None:
    """清空上下文（后台任务/测试结束时使用）"""
    _company_id.set(None)


def get_company_id() -> int | None:
    return _company_id.get()


def require_company_id() -> int:
    company_id = _company_id.get()
    if company_id is None:
        raise RuntimeError("缺少公司上下文（company_id），请确认已登录或任务已传入公司")
    return company_id
