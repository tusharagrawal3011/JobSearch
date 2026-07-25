"""Outreach Composer Agent — DRAFT ONLY, forever (for now).

For each human-CONFIRMED contact of an application, drafts a short LinkedIn message and a
slightly longer email referencing the specific role + company. The email is created as a
Gmail DRAFT via drafts.create (never send). The LinkedIn text is stored for Tushar to copy
and send himself. Both surface in the dashboard's Outreach queue.
"""
from __future__ import annotations

import json

from backend import config
from backend.db.database import get_conn, log_run, now_iso
from backend.integrations import gmail
from backend.llm import claude

AGENT = "outreach_composer"

_SYSTEM = (
    f"You draft brief, warm, specific professional outreach for {config.OWNER_NAME} "
    f"({config.OWNER_PROFILE}) who has just applied to a role. Reference the specific company "
    "and role. No flattery filler, no generic 'I came across your profile'. "
    f"Their LinkedIn is {config.OWNER_LINKEDIN}. "
    "Return JSON: {linkedin:{text}, email:{subject, body}}. "
    "LinkedIn message <= 500 chars (connection-note friendly). Email 90-150 words, "
    f"plain text, signed off as {config.OWNER_NAME}. Both must sound human, not templated."
)


def compose_for_contact(contact_id: int, create_gmail_draft: bool = True) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT ct.*, c.name AS company FROM contacts ct
               JOIN companies c ON c.id=ct.company_id WHERE ct.id=?""", (contact_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "contact not found"}
        contact = dict(row)
        if not contact["verified_by_human"]:
            return {"ok": False, "error": "contact not human-verified yet"}
        # Find the related application (most recent for this company).
        app = conn.execute(
            """SELECT a.id, j.title FROM applications a JOIN jobs j ON j.id=a.job_id
               WHERE j.company_id=? ORDER BY a.applied_at DESC LIMIT 1""",
            (contact["company_id"],)).fetchone()
        if not app:
            return {"ok": False, "error": "no application for this contact's company"}
        app = dict(app)
        # Skip if already drafted.
        dup = conn.execute("SELECT COUNT(*) n FROM outreach_drafts WHERE contact_id=?",
                           (contact_id,)).fetchone()["n"]
        if dup:
            return {"ok": True, "skipped": "already drafted", "contact_id": contact_id}

    drafts = claude.complete_json(
        f"Contact: {contact['name']} ({contact.get('role_guess','')}) at {contact['company']}.\n"
        f"Role I applied to: {app['title']}.\n"
        f"Contact public profile: {contact.get('public_profile_url','')}\n"
        "Draft the LinkedIn message and the email.",
        system=_SYSTEM, tier="smart", max_tokens=1500,
    )

    li = (drafts.get("linkedin") or {}).get("text", "")
    em = drafts.get("email") or {}
    gmail_draft_id = None
    note = ""

    # Email draft -> Gmail draft (never send). Only if we can infer a to-address; otherwise
    # store the body and let Tushar add the recipient in Gmail.
    if create_gmail_draft:
        try:
            to = _guess_email(contact) or config.OWNER_EMAIL  # self-draft if unknown
            gmail_draft_id = gmail.create_draft(to, em.get("subject", ""), em.get("body", ""))
        except Exception as e:  # noqa: BLE001
            note = f"Gmail draft not created ({e}); email text saved for manual send."

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO outreach_drafts
               (contact_id, application_id, channel, draft_text, subject_line, gmail_draft_id, status, created_at)
               VALUES (?,?, 'email', ?, ?, ?, 'drafted', ?)""",
            (contact_id, app["id"], em.get("body", ""), em.get("subject", ""), gmail_draft_id, now_iso()),
        )
        conn.execute(
            """INSERT INTO outreach_drafts
               (contact_id, application_id, channel, draft_text, subject_line, status, created_at)
               VALUES (?,?, 'linkedin', ?, NULL, 'drafted', ?)""",
            (contact_id, app["id"], li, now_iso()),
        )
        log_run(conn, AGENT, f"contact={contact_id}",
                output_ref=f"gmail_draft={gmail_draft_id or 'none'}", error_text=note)

    return {"ok": True, "contact_id": contact_id, "gmail_draft_id": gmail_draft_id,
            "gmail_draft_url": gmail.draft_url(gmail_draft_id) if gmail_draft_id else None, "note": note}


def _guess_email(contact: dict) -> str | None:
    url = (contact.get("public_profile_url") or "")
    if url.startswith("mailto:"):
        return url[len("mailto:"):]
    return None


def run() -> dict:
    """Draft outreach for every human-verified contact that has no drafts yet."""
    processed = 0
    with get_conn() as conn:
        rows = [dict(r) for r in conn.execute(
            """SELECT id FROM contacts WHERE verified_by_human=1
               AND NOT EXISTS (SELECT 1 FROM outreach_drafts d WHERE d.contact_id=contacts.id)"""
        ).fetchall()]
    for r in rows:
        compose_for_contact(r["id"])
        processed += 1
    return {"agent": AGENT, "ok": True, "processed": processed}
