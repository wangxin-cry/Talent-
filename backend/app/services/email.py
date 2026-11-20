"""
邮件发送

设计：
- 只用标准库 smtplib，异步通过 asyncio.to_thread 包装，不引入额外依赖
- EMAIL_HOST 为空即开发模式：不发信，由调用方把链接写日志
- QQ 邮箱等要求发件人等于登录账号，发件地址默认回落到 EMAIL_USERNAME
"""
from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from loguru import logger

from app.core.config import settings


def _send_sync(to: str, subject: str, text: str, html: str | None = None) -> None:
    """同步发送（在线程池里执行）"""
    from_addr = settings.email_from
    if not from_addr:
        raise RuntimeError("未配置 EMAIL_FROM_ADDRESS / EMAIL_USERNAME")

    # QQ/163 等要求发件头必须与登录账号一致，不一致时回退到登录账号
    if (
        settings.EMAIL_FROM_ADDRESS
        and settings.EMAIL_USERNAME
        and settings.EMAIL_FROM_ADDRESS.lower() != settings.EMAIL_USERNAME.lower()
    ):
        logger.warning(
            f"EMAIL_FROM_ADDRESS({settings.EMAIL_FROM_ADDRESS}) 与登录账号不一致，"
            f"改用 {settings.EMAIL_USERNAME} 发送，避免被服务商拒信"
        )
        from_addr = settings.EMAIL_USERNAME

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.EMAIL_FROM_NAME, from_addr)) if settings.EMAIL_FROM_NAME else from_addr
    msg["To"] = to
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if settings.EMAIL_USE_SSL:
        server: smtplib.SMTP = smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=20)
    else:
        server = smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=20)
        if settings.EMAIL_USE_TLS:
            server.starttls()

    try:
        if settings.EMAIL_USERNAME:
            server.login(settings.EMAIL_USERNAME, settings.EMAIL_PASSWORD)
        server.send_message(msg)
    finally:
        server.quit()


async def send_mail(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """发送邮件；开发模式或失败时返回 False（不抛异常打断主流程）"""
    if not settings.email_enabled:
        logger.warning(f"邮件未启用（EMAIL_HOST 为空），跳过发送: {subject}")
        return False

    try:
        await asyncio.to_thread(_send_sync, to, subject, text, html)
        logger.info(f"邮件已发送: {subject}")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"邮件发送失败: {type(exc).__name__}: {exc}")
        return False


def _wrap_html(title: str, body_lines: list[str], link: str, button_text: str) -> str:
    content = "".join(f"<p>{line}</p>" for line in body_lines)
    return f"""
    <div style="font-family:-apple-system,'Segoe UI','Microsoft YaHei',sans-serif;line-height:1.7;color:#1e2430">
      <h2 style="color:#4f46e5">{title}</h2>
      {content}
      <p style="margin:26px 0">
        <a href="{link}" style="display:inline-block;padding:10px 20px;border-radius:8px;
           background:#4f46e5;color:#fff;text-decoration:none">{button_text}</a>
      </p>
      <p style="font-size:12px;color:#9aa1ad">链接无法点击时请复制到浏览器打开：<br>{link}</p>
      <p style="font-size:12px;color:#9aa1ad">若非本人操作，请忽略本邮件。</p>
    </div>
    """


async def send_verification_email(to: str, name: str, link: str) -> bool:
    """发送注册邮箱验证邮件"""
    minutes = settings.EMAIL_VERIFY_EXPIRE_HOURS * 60
    text = (
        f"{name}，你好：\n\n"
        f"请点击以下链接完成邮箱验证（{settings.EMAIL_VERIFY_EXPIRE_HOURS} 小时内有效）：\n{link}\n\n"
        "若非本人操作，请忽略本邮件。"
    )
    html = _wrap_html(
        "验证你的邮箱",
        [f"{name}，你好：", f"请在 {settings.EMAIL_VERIFY_EXPIRE_HOURS} 小时内点击下方按钮完成邮箱验证。"],
        link,
        "验证邮箱",
    )
    logger.debug(f"验证链接有效期 {minutes} 分钟")
    return await send_mail(to, "【TalentMatch】邮箱验证", text, html)


async def send_reset_password_email(to: str, name: str, link: str) -> bool:
    """发送密码重置邮件"""
    text = (
        f"{name}，你好：\n\n"
        f"请点击以下链接重置密码（{settings.RESET_TOKEN_EXPIRE_MINUTES} 分钟内有效，仅可使用一次）：\n{link}\n\n"
        "若非本人操作，请忽略本邮件，你的密码不会被修改。"
    )
    html = _wrap_html(
        "重置密码",
        [
            f"{name}，你好：",
            f"请在 {settings.RESET_TOKEN_EXPIRE_MINUTES} 分钟内点击下方按钮设置新密码，链接仅可使用一次。",
        ],
        link,
        "重置密码",
    )
    return await send_mail(to, "【TalentMatch】密码重置", text, html)
