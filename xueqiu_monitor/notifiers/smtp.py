"""SMTP 邮件。"""

import logging
import smtplib
from email.message import EmailMessage

from xueqiu_monitor.notifiers.base import TextChannel, enabled, env, flag, optional_int, reject

logger = logging.getLogger(__name__)


class SmtpNotifier(TextChannel):
    name = "邮件"
    timeout = 15

    def __init__(self, host: str, port: int, user: str, password: str, sender: str, recipients: list[str], use_ssl: bool, starttls: bool):
        super().__init__()
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender = sender
        self.recipients = recipients
        self.use_ssl = use_ssl
        self.starttls = starttls

    def deliver(self, text: str, title: str) -> bool:
        message = EmailMessage()
        message["Subject"] = title[:200]
        message["From"] = self.sender
        message["To"] = ", ".join(self.recipients)
        message.set_content(text)
        client = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout) if self.use_ssl else smtplib.SMTP(self.host, self.port, timeout=self.timeout)
        try:
            if self.starttls and not self.use_ssl:
                client.starttls()
            if self.user:
                client.login(self.user, self.password)
            client.send_message(message)
            return True
        except Exception as exc:
            logger.error(f"邮件发送失败: {type(exc).__name__}")
            return False
        finally:
            try:
                client.quit()
            except Exception:
                pass


def from_env(errors: list[str]) -> SmtpNotifier | None:
    if not enabled("SMTP_ENABLED"):
        return None
    host = env("SMTP_HOST")
    sender = env("SMTP_FROM")
    raw_to = env("SMTP_TO")
    recipients = [item.strip() for item in raw_to.split(",") if item.strip()]
    if not host or not sender or not recipients:
        reject(errors, "已启用邮件，但 SMTP_HOST、SMTP_FROM 或 SMTP_TO 未配置")
        return None
    user = env("SMTP_USER")
    password = env("SMTP_PASSWORD")
    if bool(user) != bool(password):
        reject(errors, "SMTP_USER 和 SMTP_PASSWORD 需要同时配置")
        return None
    use_ssl = flag("SMTP_SSL", False)
    starttls = flag("SMTP_STARTTLS", not use_ssl)
    port = optional_int("SMTP_PORT", 465 if use_ssl else 587)
    if port is None:
        reject(errors, "SMTP_PORT 不是整数")
        return None
    return SmtpNotifier(host, port, user, password, sender, recipients, use_ssl, starttls and not use_ssl)
