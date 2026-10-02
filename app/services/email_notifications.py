"""Transactional support-email notification with a strict recipient allow-list."""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailNotificationService:
    @staticmethod
    async def send_support_reply(*, recipient: str | None, subject: str, body: str) -> bool:
        settings = get_settings()
        if not settings.smtp_enabled or not recipient:
            return False
        recipient_domain = recipient.rpartition("@")[2].lower()
        if not recipient_domain or recipient_domain not in settings.smtp_recipient_domain_set:
            logger.warning("Support email was skipped: recipient domain is not allow-listed")
            return False

        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = recipient
        message["Subject"] = f"Поддержка: {subject}"
        message.set_content(body)
        try:
            await asyncio.to_thread(EmailNotificationService._send, settings.smtp_host, settings.smtp_port, message)
        except (OSError, smtplib.SMTPException):
            logger.exception("Unable to send support email")
            return False
        return True

    @staticmethod
    def _send(host: str, port: int, message: EmailMessage) -> None:
        with smtplib.SMTP(host, port, timeout=10) as client:
            client.send_message(message)
