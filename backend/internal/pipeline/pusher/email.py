"""
Email pusher - send HTML and plain text emails via SMTP.
"""
from internal.config.settings import settings
from internal.infrastructure.monitoring.logger import get_logger

logger = get_logger("email_pusher")


class EmailPusher:
    async def push(self, recipients: list[str], subject: str, body: str, html_body: str | None = None) -> bool:
        if not settings.smtp_host or not settings.smtp_user:
            logger.warning("email push skipped: smtp not configured")
            return False

        try:
            _send_sync(recipients, subject, body, html_body)
            logger.info("email sent: recipients=%s subject=%s", recipients, subject)
            return True
        except Exception as exc:
            logger.error("email send failed: %s", exc)
            return False


def _send_sync(recipients: list[str], subject: str, body: str, html_body: str | None):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from or settings.smtp_user
    msg["To"] = ", ".join(recipients)

    msg.attach(MIMEText(body, "plain", "utf-8"))
    if html_body:
        msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        server.ehlo()
        if settings.smtp_use_tls:
            try:
                server.starttls()
                server.ehlo()
            except Exception:
                # Some SMTP servers don't require/expect STARTTLS
                pass
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.sendmail(msg["From"], recipients, msg.as_string())
