import os
import smtplib
from email.message import EmailMessage
from typing import Optional


def send_email(to_email: str, subject: str, body: str) -> Optional[str]:
    """
    Send an email using SMTP credentials in environment variables.
    Returns None on success, or a string error message on failure.
    """
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = os.getenv("FROM_EMAIL", smtp_user)
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

    if not smtp_host or not smtp_user or not smtp_password or not from_email:
        return "SMTP credentials are not fully configured."

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        # Use SSL for port 465; STARTTLS otherwise
        if not use_tls and smtp_port == 465:
            smtp_cls = smtplib.SMTP_SSL
        else:
            smtp_cls = smtplib.SMTP

        with smtp_cls(smtp_host, smtp_port, timeout=20) as server:
            if use_tls and smtp_cls is smtplib.SMTP:
                server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return None
    except Exception as exc:  # pragma: no cover - external service
        return str(exc)
