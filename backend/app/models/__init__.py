"""
模型注册入口

create_all 之前必须导入全部模型，否则表不会被创建。
新增模型时：在下方 import 并加入 __all__。
"""
from app.models.base import (  # noqa: F401
    CompanyScopedMixin,
    IdMixin,
    TimestampMixin,
    utcnow,
)

__all__ = [
    "IdMixin",
    "TimestampMixin",
    "CompanyScopedMixin",
    "utcnow",
]
