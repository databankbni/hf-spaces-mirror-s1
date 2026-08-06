# ---------------------------------------------------------------------------
# reminders/mailer.py — Phase C3.
#
# Sends reminder emails over SMTP using only the Python standard library.
# SMTP settings come from environment variables (set as Space secrets in
# production, or exported locally for testing):
#
#   SMTP_HOST       e.g. smtp.gmail.com
#   SMTP_PORT       e.g. 587
#   SMTP_USER       login username (often the from-address)
#   SMTP_PASSWORD   app password (NEVER a real account password)
#   SMTP_FROM       from-address shown to recipients (defaults to SMTP_USER)
#
# For Gmail: enable 2FA, create an App Password, and use that as
# SMTP_PASSWORD. See README for setup.
# ---------------------------------------------------------------------------

import os
import smtplib
from email.message import EmailMessage


class SMTPConfigError(RuntimeError):
    """Raised when required SMTP settings are missing."""


def _smtp_settings() -> dict:
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not (host and user and password):
        raise SMTPConfigError(
            "Missing SMTP settings. Set SMTP_HOST, SMTP_USER and "
            "SMTP_PASSWORD (as Space secrets or local env vars)."
        )
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": user,
        "password": password,
        "from_addr": os.environ.get("SMTP_FROM", user),
    }


def build_message(to_email: str, subject: str, body: str, from_addr: str) -> EmailMessage:
    """Construct an EmailMessage. Separated out so tests can assert the
    message format without sending anything."""
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def send_email(to_email: str, subject: str, body: str) -> None:
    """Send one email via SMTP with STARTTLS. Raises SMTPConfigError if
    settings are missing, or smtplib exceptions on transport failure."""
    cfg = _smtp_settings()
    msg = build_message(to_email, subject, body, cfg["from_addr"])
    with smtplib.SMTP(cfg["host"], cfg["port"]) as server:
        server.starttls()
        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)


def build_reminder(to_email: str, resume_ref: str, space_url: str) -> tuple[str, str]:
    """Return (subject, body) for a reading reminder. `resume_ref` is a
    human reference like 'BG 2.47'."""
    subject = "Your Bhagavad Gita reading is waiting"
    body = (
        f"Namaste,\n\n"
        f"It's time for today's Bhagavad Gita reading. "
        f"You left off at {resume_ref}.\n\n"
        f"Continue here: {space_url}\n\n"
        f"— Bhagwad Gita Reading Agent\n"
    )
    return subject, body
