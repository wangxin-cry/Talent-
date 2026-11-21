"""对话式入口请求 / 响应模型（阶段九½）"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- 会话
class ChatSessionCreateIn(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    context_job_id: int | None = None
    context_candidate_id: int | None = None


class ChatSessionUpdateIn(BaseModel):
    title: str | None = Field(default=None, max_length=100)
    context_job_id: int | None = None
    context_candidate_id: int | None = None


class ChatSessionOut(BaseModel):
    id: int
    title: str | None = None
    context_job_id: int | None = None
    context_candidate_id: int | None = None
    last_message_at: datetime | None = None
    create_time: datetime
    update_time: datetime
    message_count: int = 0
    last_message: str | None = None


class ChatSessionListOut(BaseModel):
    items: list[ChatSessionOut] = []
    total: int = 0


class ChatMessageOut(BaseModel):
    id: int
    session_id: int
    role: str
    content: str | None = None
    card_type: str | None = None
    card_data: dict = {}
    intent: str | None = None
    trace_id: str | None = None
    tokens: int = 0
    cost: float = 0.0
    create_time: datetime


class ChatSessionDetailOut(BaseModel):
    session: ChatSessionOut
    messages: list[ChatMessageOut] = []


# ---------------------------------------------------------------- 发消息
class ChatSendIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    file_ids: list[int] = Field(default_factory=list, description="随消息上传的文件 id")
    context_job_id: int | None = Field(default=None, description="覆盖会话当前职位")
    context_candidate_id: int | None = Field(
        default=None, description="覆盖会话当前候选人"
    )
    use_llm: bool = Field(default=False, description="是否允许子 Agent 调用 LLM")


class ChatSendOut(BaseModel):
    session: ChatSessionOut
    user_message: ChatMessageOut
    replies: list[ChatMessageOut] = []
    intent: str | None = None
    intent_label: str | None = None
    confidence: float = 0.0
    needs_clarification: bool = False
    trace_id: str | None = None
    degraded: bool = False
    duration_ms: int = 0
    total_cost: float = 0.0


class ChatStreamStartOut(BaseModel):
    task_id: str
    session_id: int


# ---------------------------------------------------------------- 确认
class ChatConfirmIn(BaseModel):
    message_id: int = Field(description="待确认卡片的助手消息 id")
    note: str | None = Field(default=None, max_length=1000, description="淘汰原因 / 备注")
    offer_salary: int | None = Field(default=None, ge=0, le=1000)


class ChatConfirmOut(BaseModel):
    message: ChatMessageOut
    trace_id: str | None = None
    degraded: bool = False


# ---------------------------------------------------------------- 工具注册表
class ChatToolOut(BaseModel):
    name: str
    label: str
    description: str
    level: str = Field(description="read / write / irreversible")
    parameters: dict = {}


class ChatToolListOut(BaseModel):
    items: list[ChatToolOut] = []


class ChatIntentOut(BaseModel):
    intent: str
    label: str
    level: str
    tool: str


class ChatIntentListOut(BaseModel):
    items: list[ChatIntentOut] = []
