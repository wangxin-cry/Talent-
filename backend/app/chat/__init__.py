"""对话式入口（Chat Gateway，阶段九½）

- 工具注册表：把阶段三~七能力封装成带 schema 的工具
- 对话引擎：意图识别 → 槽位抽取 → 缺参追问 → 安全闸 → 编排 → 卡片
"""
from app.chat.engine import (  # noqa: F401
    confirm_action,
    get_session_or_404,
    handle_message,
    message_out,
    session_payload,
    session_payloads,
)
from app.chat.nlu import INTENT_META  # noqa: F401
from app.chat.tools import tool_table  # noqa: F401

__all__ = [
    "handle_message",
    "confirm_action",
    "get_session_or_404",
    "session_payload",
    "session_payloads",
    "message_out",
    "tool_table",
    "INTENT_META",
]
