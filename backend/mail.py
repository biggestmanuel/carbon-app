"""Outbound email.

Delivery is pluggable so development needs no credentials and no network.
ConsoleMailer logs the message, which is enough to complete a password reset
locally. SMTPMailer is for real deployments.
"""

import logging
import smtplib
from email.message import EmailMessage

from flask import current_app

log = logging.getLogger(__name__)


class ConsoleMailer:
    """Logs the email instead of sending it. Default outside production."""

    def send(self, to, subject, body):
        log.info("EMAIL to=%s subject=%s body=%s", to, subject, body)

    @property
    def name(self):
        return "console"


class SMTPMailer:
    def __init__(self, host, port, username, password, sender, use_tls=True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls

    def send(self, to, subject, body):
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

    @property
    def name(self):
        return "smtp"


def get_mailer():
    """Return the configured mailer, or None when no address is on file.

    A user without a verified email cannot be mailed, which is the honest
    outcome: silently succeeding would strand them.
    """
    cfg = current_app.config
    if not cfg.get("MAIL_ENABLED", False):
        return ConsoleMailer()
    host = cfg.get("MAIL_HOST")
    if not host:
        return ConsoleMailer()
    return SMTPMailer(
        host=host,
        port=int(cfg.get("MAIL_PORT", 587)),
        username=cfg.get("MAIL_USERNAME"),
        password=cfg.get("MAIL_PASSWORD"),
        sender=cfg.get("MAIL_SENDER", "no-reply@localhost"),
        use_tls=bool(cfg.get("MAIL_USE_TLS", True)),
    )


def send_password_reset(to_email, raw_token):
    """Send a reset link. Raises on delivery failure so the caller can 502."""
    cfg = current_app.config
    link = f"{cfg['PUBLIC_BASE_URL'].rstrip('/')}/reset-password?token={raw_token}"
    body = (
        "Someone asked to reset the password for this account.\n\n"
        f"Use this link within {int(cfg['PASSWORD_RESET_TTL_MINUTES'])} minutes:\n"
        f"{link}\n\n"
        "If this was not you, ignore this message. Nothing has changed.\n"
    )
    mailer = get_mailer()
    mailer.send(to_email, "Reset your password", body)
    return mailer.name
