"""
模型注册入口

create_all 之前必须导入全部模型，否则表不会被创建。
"""
from app.models.ai_call import (  # noqa: F401
    AI_STATUS_FAILED,
    AI_STATUS_SKIPPED,
    AI_STATUS_SUCCESS,
    AiCall,
)
from app.models.application import (  # noqa: F401
    APP_HIRED,
    APP_INTERVIEW,
    APP_NEW,
    APP_OFFER,
    APP_REJECTED,
    APP_SCREENING,
    APP_STATUS_LABELS,
    APP_STATUSES,
    APP_TRANSITIONS,
    Application,
    ApplicationStageHistory,
)
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
from app.models.interview_question import InterviewQuestion  # noqa: F401
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
from app.models.notification import (  # noqa: F401
    NOTIF_CHANNEL_EMAIL,
    NOTIF_CHANNEL_INAPP,
    NOTIF_FAILED,
    NOTIF_PENDING,
    NOTIF_READ,
    NOTIF_SENT,
    Notification,
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
    "IdMixin", "TimestampMixin", "CompanyScopedMixin", "utcnow",
    "User", "AuthToken", "Skill", "Job",
    "Candidate", "ResumeFile", "Resume", "AuditLog", "MatchResult",
    "Application", "ApplicationStageHistory", "Notification", "InterviewQuestion",
    "AiCall",
    "AI_STATUS_SUCCESS", "AI_STATUS_FAILED", "AI_STATUS_SKIPPED",
    "RF_PENDING", "RF_PARSING", "RF_SUCCESS", "RF_FAILED", "FILE_STATUS_LABELS",
    "STATUS_DRAFT", "STATUS_PENDING", "STATUS_PUBLISHED", "STATUS_CLOSED", "STATUS_ARCHIVED",
    "JD_SOURCE_MANUAL", "JD_SOURCE_AI", "WORK_MODES", "EMPLOYMENT_TYPES", "EDUCATION_LEVELS",
    "CATEGORY_LANGUAGE", "CATEGORY_FRAMEWORK", "CATEGORY_DATABASE",
    "CATEGORY_MIDDLEWARE", "CATEGORY_TOOL", "CATEGORY_SOFT",
    "ROLE_RECRUITER", "ROLE_MANAGER", "ROLE_ADMIN", "STATUS_ACTIVE", "STATUS_DISABLED",
    "PURPOSE_VERIFY_EMAIL", "PURPOSE_RESET_PASSWORD",
    "APP_NEW", "APP_SCREENING", "APP_INTERVIEW", "APP_OFFER", "APP_HIRED", "APP_REJECTED",
    "APP_STATUSES", "APP_STATUS_LABELS", "APP_TRANSITIONS",
    "NOTIF_CHANNEL_INAPP", "NOTIF_CHANNEL_EMAIL",
    "NOTIF_PENDING", "NOTIF_SENT", "NOTIF_FAILED", "NOTIF_READ",
]
