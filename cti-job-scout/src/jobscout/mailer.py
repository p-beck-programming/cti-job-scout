"""Send the digest via the Gmail API using OAuth2 (no SMTP passwords).

Auth model: a one-time locally-generated refresh token (see
scripts/get_gmail_refresh_token.py) is stored as a secret; each run mints a
short-lived access token from it. Scope is gmail.send only — the token can
send mail as you but can never read your inbox, which limits blast radius
if the secret ever leaks.

Google libraries are imported lazily so the rest of the pipeline (and the
test suite) doesn't require them.
"""

from __future__ import annotations

import base64
import logging
import os
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


class MailConfigError(Exception):
    pass


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise MailConfigError(f"Missing required environment variable: {name}")
    return value


def build_message(subject: str, html_body: str, recipient: str) -> dict:
    """Assemble the Gmail API message payload (pure function; unit-testable)."""
    msg = MIMEText(html_body, "html")
    msg["to"] = recipient
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def send_digest(subject: str, html_body: str) -> None:
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    recipient = _require_env("DIGEST_RECIPIENT")
    creds = Credentials(
        token=None,  # will be refreshed on first use
        refresh_token=_require_env("GMAIL_REFRESH_TOKEN"),
        client_id=_require_env("GMAIL_CLIENT_ID"),
        client_secret=_require_env("GMAIL_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=GMAIL_SCOPES,
    )
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    message = build_message(subject, html_body, recipient)
    result = service.users().messages().send(userId="me", body=message).execute()
    log.info("Digest sent to %s (Gmail message id %s)", recipient, result.get("id"))
