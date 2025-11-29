import os
import smtplib
from email.message import EmailMessage
from typing import Optional

import requests


def send_email(to_email: str, subject: str, body: str) -> Optional[str]:
    """
    Send an email using SMTP credentials in environment variables.
    If SENDGRID_API_KEY is set, prefer SendGrid's Web API to avoid SMTP networking issues.
    Returns None on success, or a string error message on failure.
    """
    sg_api_key = os.getenv("SENDGRID_API_KEY")
    from_email_env = os.getenv("FROM_EMAIL")
    if sg_api_key and from_email_env:
        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {sg_api_key}", "Content-Type": "application/json"},
                json={
                    "personalizations": [{"to": [{"email": to_email}]}],
                    "from": {"email": from_email_env},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
                timeout=15,
            )
            if resp.status_code in (200, 202):
                return None
            # If API fails, fall back to SMTP
        except Exception as exc:  # pragma: no cover - external service
            pass

    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    from_email = from_email_env or smtp_user
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
