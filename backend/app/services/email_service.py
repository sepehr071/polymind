import html
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from email_validator import EmailNotValidError, validate_email

_logger = logging.getLogger(__name__)


def _valid_recipient(to: str) -> str | None:
    """Return the normalized recipient address, or ``None`` if it is not a
    single, syntactically-valid address.

    ``validate_email`` rejects control chars, surrounding/embedded whitespace,
    and anything that is not exactly one address (a comma-separated list fails
    to parse), which closes header/recipient-list smuggling at the envelope.
    ``check_deliverability=False`` keeps it a pure syntax check — no DNS lookup
    (the prod host is air-gapped; a DNS round-trip would hang/fail).
    """
    if not to or not isinstance(to, str):
        return None
    try:
        return validate_email(to, check_deliverability=False).normalized
    except EmailNotValidError:
        return None


def send_invite_email(
    to: str,
    workspace_name: str,
    accept_url: str,
    inviter_name: str,
    role: str,
) -> bool:
    """Send a workspace invite email. Returns True on success, False otherwise.

    If SMTP_HOST is not configured, logs an info message and returns False so
    the caller can render a "copy link" fallback without raising.
    """
    smtp_host = os.environ.get('SMTP_HOST', '').strip()
    if not smtp_host:
        _logger.info("SMTP not configured; skipping invite email to %s", to)
        return False

    recipient = _valid_recipient(to)
    if recipient is None:
        _logger.warning("Refusing invite email to invalid recipient address %r", to)
        return False

    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER', '')
    smtp_pass = os.environ.get('SMTP_PASS', '')
    smtp_from = os.environ.get('SMTP_FROM', smtp_user)

    subject = f"You're invited to {workspace_name}"

    plain = (
        f"Hi,\n\n"
        f"{inviter_name} has invited you to join {workspace_name} as {role}.\n\n"
        f"Accept your invitation:\n{accept_url}\n\n"
        f"This link expires in 7 days."
    )
    # workspace_name (and inviter_name/role) are owner-controlled; escape before
    # interpolating into the HTML part so a crafted company name can't inject
    # markup/phishing links sent from our SPF/DKIM-aligned domain.
    safe_inviter = html.escape(inviter_name or '')
    safe_workspace = html.escape(workspace_name or '')
    safe_role = html.escape(role or '')
    html_body = (
        f"<p>Hi,</p>"
        f"<p><strong>{safe_inviter}</strong> has invited you to join "
        f"<strong>{safe_workspace}</strong> as <em>{safe_role}</em>.</p>"
        f"<p><a href=\"{accept_url}\">Accept invitation</a></p>"
        f"<p>This link expires in 7 days.</p>"
    )

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = smtp_from
    msg['To'] = recipient
    msg.attach(MIMEText(plain, 'plain'))
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_from, [recipient], msg.as_string())
        return True
    except Exception:
        _logger.warning("Failed to send invite email to %s", recipient, exc_info=True)
        return False
