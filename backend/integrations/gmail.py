"""Gmail API integration — used two ways, each least-privilege:

  1. read-only inbox access (messages.list/get) for the Email Alert Parser.
  2. drafts.create ONLY for the Outreach Composer.

This module NEVER calls messages.send. There is no send() function here by design.
"""
from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Optional

from backend import config


def is_configured() -> bool:
    """True if Gmail can be used without prompting for interactive OAuth — i.e. a cached
    token exists, or an OAuth client secret is present to run consent once. When this is
    False, Gmail-dependent agents skip gracefully instead of launching a browser flow."""
    return config.GMAIL_TOKEN_JSON.exists() or config.GMAIL_CREDENTIALS_JSON.exists()


def is_connected() -> bool:
    """True only once the user has completed consent (a cached token exists)."""
    return config.GMAIL_TOKEN_JSON.exists()


def connect() -> dict:
    """Run the OAuth consent flow (opens a browser once) and cache the token. Triggered by
    the dashboard's 'Connect Gmail' button. Requires credentials.json to be present."""
    if not config.GMAIL_CREDENTIALS_JSON.exists():
        return {"ok": False, "connected": False,
                "error": "credentials.json not found — add your Google OAuth client secret "
                         "(Desktop app) to the project root first."}
    try:
        svc = _service()   # opens the consent browser if there's no cached token yet
        prof = svc.users().getProfile(userId="me").execute()
        return {"ok": True, "connected": True, "email": prof.get("emailAddress")}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "connected": False, "error": str(e)}


def _service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds: Optional[Credentials] = None
    if config.GMAIL_TOKEN_JSON.exists():
        creds = Credentials.from_authorized_user_file(str(config.GMAIL_TOKEN_JSON), config.GMAIL_SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.GMAIL_CREDENTIALS_JSON.exists():
                raise RuntimeError(
                    f"Gmail credentials not found at {config.GMAIL_CREDENTIALS_JSON}. "
                    "Download an OAuth client secret from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.GMAIL_CREDENTIALS_JSON), config.GMAIL_SCOPES
            )
            creds = flow.run_local_server(port=0)
        config.GMAIL_TOKEN_JSON.write_text(creds.to_json(), encoding="utf-8")
    return build("gmail", "v1", credentials=creds)


# ---------------- Read side (Email Alert Parser) ----------------

def list_alert_messages(window_hours: int, sender_domains: list[str]) -> list[str]:
    """Return message IDs from the alert senders within the recency window."""
    svc = _service()
    from_clause = " OR ".join(f"from:{d}" for d in sender_domains)
    query = f"({from_clause}) newer_than:{max(1, window_hours // 24 or 1)}d"
    ids: list[str] = []
    resp = svc.users().messages().list(userId="me", q=query, maxResults=100).execute()
    ids.extend(m["id"] for m in resp.get("messages", []))
    return ids


def search_messages(query: str, max_results: int = 250) -> list[dict]:
    """Search the mailbox and return lightweight metadata (id, sender, subject, date,
    snippet) — no body fetch, so it's fast enough to scan hundreds of messages."""
    svc = _service()
    ids: list[str] = []
    resp = svc.users().messages().list(userId="me", q=query, maxResults=100).execute()
    ids.extend(m["id"] for m in resp.get("messages", []))
    while resp.get("nextPageToken") and len(ids) < max_results:
        resp = svc.users().messages().list(
            userId="me", q=query, pageToken=resp["nextPageToken"], maxResults=100).execute()
        ids.extend(m["id"] for m in resp.get("messages", []))

    out: list[dict] = []
    for mid in ids[:max_results]:
        m = svc.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        headers = {h["name"].lower(): h["value"] for h in m["payload"].get("headers", [])}
        out.append({
            "id": mid,
            "sender": headers.get("from", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "snippet": m.get("snippet", ""),
        })
    return out


def get_message(msg_id: str) -> dict:
    """Return {'sender','subject','date','body_html','body_text'} for a message."""
    svc = _service()
    msg = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}
    html, text = _extract_body(msg["payload"])
    return {
        "id": msg_id,
        "sender": headers.get("from", ""),
        "subject": headers.get("subject", ""),
        "date": headers.get("date", ""),
        "body_html": html,
        "body_text": text,
    }


def _extract_body(payload: dict) -> tuple[str, str]:
    html, text = "", ""
    stack = [payload]
    while stack:
        part = stack.pop()
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data.encode()).decode("utf-8", "ignore")
            if mime == "text/html":
                html += decoded
            elif mime == "text/plain":
                text += decoded
        stack.extend(part.get("parts", []))
    return html, text


# ---------------- Draft side (Outreach Composer) ----------------

def create_draft(to: str, subject: str, body: str, from_addr: Optional[str] = None) -> str:
    """Create a Gmail DRAFT (never sent). Returns the draft id."""
    svc = _service()
    mime = MIMEText(body)
    mime["to"] = to
    mime["from"] = from_addr or config.OWNER_EMAIL
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    draft = svc.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
    return draft["id"]


def draft_url(draft_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#drafts?compose={draft_id}"
