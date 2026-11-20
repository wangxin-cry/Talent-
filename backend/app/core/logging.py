"""
日志配置

要点：
1. loguru 统一输出，结构化字段便于排查；
2. 提供 PII 脱敏工具（手机/邮箱/姓名），日志里禁止出现明文个人信息。
"""
from __future__ import annotations

import re
import sys

from loguru import logger

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
_EMAIL_RE = re.compile(r"([A-Za-z0-9._%+-]{1,2})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def mask_phone(text: str) -> str:
    """手机号脱敏：13800000001 -> 138****0001"""
    return _PHONE_RE.sub(lambda m: f"{m.group(1)}****{m.group(3)}", text)


def mask_email(text: str) -> str:
    """邮箱脱敏：zhangwei@example.com -> zh***@example.com"""
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)}***{m.group(2)}", text)


def mask_pii(text: str) -> str:
    """统一 PII 脱敏（日志输出前调用）"""
    if not text:
        return text
    return mask_email(mask_phone(text))


def setup_logging() -> None:
    """初始化日志（应用启动时调用一次）"""
    logger.remove()
    logger.add(
        sys.stdout,
        level="DEBUG",
        colorize=True,
        enqueue=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )
    logger.info("日志初始化完成")


__all__ = ["logger", "setup_logging", "mask_pii", "mask_phone", "mask_email"]
