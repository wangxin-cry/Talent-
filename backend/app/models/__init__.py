"""
模型注册入口

create_all 之前必须导入全部模型，否则表不会被创建。
新增模型时：在下方 import 并加入 __all__。
"""
from app.models.auth_token import (  # noqa: F401
    PURPOSE_RESET_PASSWORD,
    PURPOSE_VERIFY_EMAIL,
    AuthToken,
)
from app.models.base import (  # noqa: F401
    CompanyScopedMixin,
    IdMixin,
    TimestampMixin,
    utcnow,
)
from app.models.job import (  # noqa: F401
    EDUCATION_LEVELS,
    EMPLOYMENT_TYPES,
    JD_SOURCE_AI,
    JD_SOURCE_MANUAL,
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_DRAFT,
    STATUS_PENDING,
    STATUS_PUBLISHED,
    WORK_MODES,
    Job,
)
from app.models.skill import (  # noqa: F401
    CATEGORY_DATABASE,
    CATEGORY_FRAMEWORK,
    CATEGORY_LANGUAGE,
    CATEGORY_MIDDLEWARE,
    CATEGORY_SOFT,
    CATEGORY_TOOL,
    Skill,
)
from app.models.user import (  # noqa: F401
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_RECRUITER,
    STATUS_ACTIVE,
    STATUS_DISABLED,
    User,
)

__all__ = [
    "IdMixin",
    "TimestampMixin",
    "CompanyScopedMixin",
    "utcnow",
    "User",
    "AuthToken",
    "Skill",
    "Job",
    "STATUS_DRAFT",
    "STATUS_PENDING",
    "STATUS_PUBLISHED",
    "STATUS_CLOSED",
    "STATUS_ARCHIVED",
    "JD_SOURCE_MANUAL",
    "JD_SOURCE_AI",
    "WORK_MODES",
    "EMPLOYMENT_TYPES",
    "EDUCATION_LEVELS",
    "CATEGORY_LANGUAGE",
    "CATEGORY_FRAMEWORK",
    "CATEGORY_DATABASE",
    "CATEGORY_MIDDLEWARE",
    "CATEGORY_TOOL",
    "CATEGORY_SOFT",
    "ROLE_RECRUITER",
    "ROLE_MANAGER",
    "ROLE_ADMIN",
    "STATUS_ACTIVE",
    "STATUS_DISABLED",
    "PURPOSE_VERIFY_EMAIL",
    "PURPOSE_RESET_PASSWORD",
]
