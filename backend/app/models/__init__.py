"""
模型注册入口

create_all 之前必须导入全部模型，否则表不会被创建。
"""
from app.models.agent_trace import (  # noqa: F401
    AGENT_ANALYTICS,
    AGENT_INTERVIEW,
    AGENT_JD_WRITER,
    AGENT_MANAGER,
    AGENT_MATCH_ENGINE,
    AGENT_RESUME_PARSER,
    AGENT_WORKFLOW,
    TRACE_DEGRADED,
    TRACE_FAILED,
    TRACE_SKIPPED,
    TRACE_SUCCESS,
    TRACE_TIMEOUT,
    AgentTrace,
)
from app.models.ai_call import (  # noqa: F401
    AI_STATUS_FAILED,
    AI_STATUS_SKIPPED,
    AI_STATUS_SUCCESS,
    AiCall,
)
from app.models.api_key import ApiKey  # noqa: F401
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
from app.models.chat import (  # noqa: F401
    CARD_CHART,
    CARD_CONFIRM,
    CARD_INTERVIEW,
    CARD_MATCH_RANK,
    CARD_PARSE_RESULT,
    CARD_TYPES,
    CARD_UPLOAD,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    ChatMessage,
    ChatSession,
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
from app.models.company import (  # noqa: F401
    STATUS_ACTIVE as COMPANY_STATUS_ACTIVE,
    STATUS_DISABLED as COMPANY_STATUS_DISABLED,
    Company,
)
from app.models.interview import (  # noqa: F401
    ApplicationTracking,
    InterviewFeedback,
    InterviewSchedule,
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
from app.models.rag_chunk import (  # noqa: F401
    DOC_JOB,
    DOC_QUESTION,
    DOC_RESUME,
    DOC_TYPE_LABELS,
    RagChunk,
)
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
from app.models.system_config import SystemConfig  # noqa: F401
from app.models.user import (  # noqa: F401
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_RECRUITER,
    ROLE_SUPERADMIN,
    STATUS_ACTIVE,
    STATUS_DELETED,
    STATUS_DISABLED,
    User,
)

__all__ = [
    "IdMixin", "TimestampMixin", "CompanyScopedMixin", "utcnow",
    "Company", "COMPANY_STATUS_ACTIVE", "COMPANY_STATUS_DISABLED",
    "ROLE_SUPERADMIN",
    "User", "AuthToken", "Skill", "Job",
    "Candidate", "ResumeFile", "Resume", "AuditLog", "MatchResult",
    "Application", "ApplicationStageHistory", "Notification", "InterviewQuestion",
    "InterviewSchedule", "InterviewFeedback", "ApplicationTracking",
    "RagChunk", "DOC_RESUME", "DOC_JOB", "DOC_QUESTION", "DOC_TYPE_LABELS",
    "AgentTrace", "ChatSession", "ChatMessage",
    "ApiKey", "SystemConfig",
    "ROLE_USER", "ROLE_ASSISTANT", "ROLE_SYSTEM",
    "CARD_UPLOAD", "CARD_PARSE_RESULT", "CARD_MATCH_RANK",
    "CARD_INTERVIEW", "CARD_CONFIRM", "CARD_CHART", "CARD_TYPES",
    "AGENT_MANAGER", "AGENT_JD_WRITER", "AGENT_RESUME_PARSER", "AGENT_MATCH_ENGINE",
    "AGENT_INTERVIEW", "AGENT_WORKFLOW", "AGENT_ANALYTICS",
    "TRACE_SUCCESS", "TRACE_FAILED", "TRACE_TIMEOUT", "TRACE_SKIPPED", "TRACE_DEGRADED",
    "AiCall",
    "AI_STATUS_SUCCESS", "AI_STATUS_FAILED", "AI_STATUS_SKIPPED",
    "RF_PENDING", "RF_PARSING", "RF_SUCCESS", "RF_FAILED", "FILE_STATUS_LABELS",
    "STATUS_DRAFT", "STATUS_PENDING", "STATUS_PUBLISHED", "STATUS_CLOSED", "STATUS_ARCHIVED",
    "JD_SOURCE_MANUAL", "JD_SOURCE_AI", "WORK_MODES", "EMPLOYMENT_TYPES", "EDUCATION_LEVELS",
    "CATEGORY_LANGUAGE", "CATEGORY_FRAMEWORK", "CATEGORY_DATABASE",
    "CATEGORY_MIDDLEWARE", "CATEGORY_TOOL", "CATEGORY_SOFT",
    "ROLE_RECRUITER", "ROLE_MANAGER", "ROLE_ADMIN", "STATUS_ACTIVE", "STATUS_DISABLED",
    "STATUS_DELETED",
    "PURPOSE_VERIFY_EMAIL", "PURPOSE_RESET_PASSWORD",
    "APP_NEW", "APP_SCREENING", "APP_INTERVIEW", "APP_OFFER", "APP_HIRED", "APP_REJECTED",
    "APP_STATUSES", "APP_STATUS_LABELS", "APP_TRANSITIONS",
    "NOTIF_CHANNEL_INAPP", "NOTIF_CHANNEL_EMAIL",
    "NOTIF_PENDING", "NOTIF_SENT", "NOTIF_FAILED", "NOTIF_READ",
]
