"""Sending account emails (confirm address, reset password, security notices) over SMTP.

Configure with environment variables:
  SMTP_HOST, SMTP_PORT (587), SMTP_SECURITY ("starttls" or "ssl"), SMTP_USERNAME, SMTP_PASSWORD,
  MAIL_FROM (e.g. "Artemis <no-reply@your-domain>"), APP_URL (the public address, e.g. https://your-domain).

Without SMTP_HOST, emails are printed to the server log instead (for local development only).
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlsplit

log = logging.getLogger("artemis.mail")

APP_URL = os.environ.get("APP_URL", "http://localhost:8000").rstrip("/")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls").lower()
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Artemis <no-reply@localhost>")
SEND_TIMEOUT = 15

OUTBOX: list[EmailMessage] = []    # console mode only: the last emails, for local testing
_pending: set[asyncio.Task] = set()


def is_local() -> bool:
    return urlsplit(APP_URL).hostname in ("localhost", "127.0.0.1", "::1")


def config_problem() -> str | None:
    """Why email can't work in this deployment, or None if it's fine."""
    if SMTP_HOST:
        if SMTP_SECURITY not in ("starttls", "ssl"):
            return "SMTP_SECURITY must be 'starttls' or 'ssl'"
        return None
    if is_local():
        return None   # console mode for local development
    return "SMTP_HOST is not set, so account emails can't be sent"


def _send_smtp(message: EmailMessage) -> None:
    context = ssl.create_default_context()
    if SMTP_SECURITY == "ssl":
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=SEND_TIMEOUT, context=context) as smtp:
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SEND_TIMEOUT) as smtp:
            smtp.starttls(context=context)   # refuse to send credentials or links in the clear
            if SMTP_USERNAME:
                smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
            smtp.send_message(message)


async def _deliver(message: EmailMessage) -> None:
    if not SMTP_HOST:
        OUTBOX.append(message)
        del OUTBOX[:-20]
        log.warning("Email not sent (no SMTP_HOST); printed for local testing:\nTo: %s\nSubject: %s\n\n%s",
                    message["To"], message["Subject"], message.get_content())
        return
    try:
        await asyncio.to_thread(_send_smtp, message)
    except (smtplib.SMTPException, OSError) as exc:
        log.error("Sending email to %s failed: %s", message["To"], exc)


def send(to: str, subject: str, body: str) -> None:
    """Queue an email and return at once, so response times don't reveal whether an account exists."""
    message = EmailMessage()
    message["From"] = MAIL_FROM
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    task = asyncio.get_running_loop().create_task(_deliver(message))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


# ---------- the emails ----------

def link(path: str, token: str) -> str:
    # The token goes after "#": browsers never send that part to the server or to other sites,
    # so it stays out of access logs and Referer headers.
    return f"{APP_URL}{path}#{token}"


def send_verification(to: str, token: str) -> None:
    send(to, "Confirm your Artemis account", f"""Confirm this email address to finish creating your Artemis account:

{link("/verify", token)}

You'll be asked for the password you chose when signing up. The link works once and expires in 24 hours.

If you didn't sign up for Artemis, ignore this email and no account will be created. If you did sign up but don't recognise the password it asks for, use "Forgot password" on the login screen instead.
""")


def send_already_registered(to: str) -> None:
    send(to, "Sign-up attempt for your Artemis account", f"""Someone tried to create an Artemis account with this email address, but you already have one.

If it was you, log in at {APP_URL} . If you've forgotten your password, or you usually use "Continue with Google", you can also choose "Forgot password" there to set one.

If it wasn't you, you don't need to do anything. Your account hasn't changed.
""")


def send_reset(to: str, token: str) -> None:
    send(to, "Reset your Artemis password", f"""To choose a new password for your Artemis account, open this link. If you sign in with Google, this adds a password; Google sign-in keeps working.

{link("/reset", token)}

The link works once and expires in 1 hour. Resetting your password signs you out on all your devices.

If you didn't ask to reset your password, ignore this email. Your password hasn't changed.
""")


def send_password_changed(to: str) -> None:
    send(to, "Your Artemis password was changed", f"""The password for your Artemis account was just changed, and every device was signed out.

If you did this, you don't need to do anything.

If you didn't, reset your password now at {APP_URL} (choose "Forgot password") and contact us at artemis_secure@gmail.com.
""")
