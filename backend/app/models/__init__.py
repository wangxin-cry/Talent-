"""
模型注册入口

create_all 之前必须导入全部模型，否则表不会被创建。
"""
from app.models.audit import AuditLog  # noqa: F401
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
from app.models.candidate import (  # noqa: F401
    FILE_STATUS_LABELS,
    RF_FAILED,
    RF_PARSING,
    RF_PENDING,
    RF_SUCCESS,
    Candidate,
    Resume,
    ResumeFile,
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
from app.models.match_result import MatchResult  # noqa: F401
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
    "IdMixin", "TimestampMixin", "CompanyScopedMixin", "utcnow",
    "User", "AuthToken", "Skill", "Job",
    "Candidate", "ResumeFile", "Resume", "AuditLog", "MatchResult",
    "RF_PENDING", "RF_PARSING", "RF_SUCCESS", "RF_FAILED", "FILE_STATUS_LABELS",
    "STATUS_DRAFT", "STATUS_PENDING", "STATUS_PUBLISHED", "STATUS_CLOSED", "STATUS_ARCHIVED",
    "JD_SOURCE_MANUAL", "JD_SOURCE_AI", "WORK_MODES", "EMPLOYMENT_TYPES", "EDUCATION_LEVELS",
    "CATEGORY_LANGUAGE", "CATEGORY_FRAMEWORK", "CATEGORY_DATABASE",
    "CATEGORY_MIDDLEWARE", "CATEGORY_TOOL", "CATEGORY_SOFT",
    "ROLE_RECRUITER", "ROLE_MANAGER", "ROLE_ADMIN", "STATUS_ACTIVE", "STATUS_DISABLED",
    "PURPOSE_VERIFY_EMAIL", "PURPOSE_RESET_PASSWORD",
]