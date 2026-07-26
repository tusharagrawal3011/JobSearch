"""Referral Finder.

For a company you're targeting, finds the best person to ask for a referral and drafts a
short, honest referral-request email grounded in your real profile. A warm referral is the
single highest-leverage move in a search, so this makes the ask fast and specific.

WHO to ask depends on company size:
  * startup / small company  -> a founder, CEO, CTO, or an engineering lead (they read their
    own inbox and can refer you directly),
  * large company / MNC      -> a senior engineer on the relevant team, an engineering
    manager, or a recruiter for that org.

Public sources ONLY — company team/about/leadership pages, GitHub, personal sites, engineering
blogs, conference/talk pages, and public LinkedIn profile URLs (linked, never scraped). An
email is reported as 'found' only when it appears on a real public page; otherwise the model may
offer a likely address as 'inferred' (with the pattern explained) — never presented as
confirmed. Emails are DRAFTED, never sent.
"""
from __future__ import annotations

import json

from backend import profile
from backend.db.database import get_conn, log_run, now_iso
from backend.llm import client

AGENT = "referral_finder"

_SENIORITY = {"founder", "exec", "manager", "senior_engineer", "recruiter", "other"}
_EMAIL_STATUS = {"found", "inferred", "none"}

_FIND_SYSTEM = (
    "You find the best person to ask for a job referral at a specific company, using ONLY public "
    "web sources: the company's team/about/leadership pages, GitHub org and member pages, personal "
    "sites, engineering-blog author bylines, conference speaker pages, and public LinkedIn profile "
    "URLs (link only — never scrape or invent profile contents). "
    "Choose WHO by company size: for a startup or small company prefer a founder / CEO / CTO / "
    "engineering lead; for a large company or MNC prefer a senior engineer on the relevant team, an "
    "engineering manager, or a recruiter for that org. Prefer people plausibly connected to the "
    "role's domain. "
    "Report an email ONLY if it appears on a real public page — then set email_status='found' and "
    "name the page in 'source'. If you can't find one but the company's address pattern is publicly "
    "evident (other real addresses on the site), you MAY provide a likely address with "
    "email_status='inferred' and explain the basis in 'email_note'. Otherwise use "
    "email_status='none' and leave email empty. NEVER present a guessed address as confirmed, and "
    "never fabricate a person, title, or URL. "
    "Return ONLY a JSON array (max 4) of objects: {name, title, seniority (one of: founder, exec, "
    "manager, senior_engineer, recruiter, other), why_them, public_profile_url, email, email_status, "
    "email_note, source}. If you find no one credible, return []."
)


def _draft_system(name: str) -> str:
    return (
        f"You write a short, warm, genuine referral-request email from {name} to someone at a "
        "company where they want to apply. HARD RULES: ground every claim in the candidate's real "
        "profile — never invent experience, titles, employers, or metrics. Be specific about the "
        "role and why this company. Respect the recipient's time: 90-140 words, an easy yes or no, "
        "and offer to share your résumé / LinkedIn. Warm and human, not templated; no clichés like "
        f"'I hope this email finds you well'. Sign as {name}. "
        "Return JSON {subject, body} — body is plain text with short paragraphs."
    )


def _clean_contact(c: dict) -> dict:
    seniority = str(c.get("seniority", "other")).lower()
    status = str(c.get("email_status", "none")).lower()
    return {
        "name": str(c.get("name", "")).strip()[:120],
        "title": str(c.get("title", "")).strip()[:160],
        "seniority": seniority if seniority in _SENIORITY else "other",
        "why_them": str(c.get("why_them", "")).strip()[:400],
        "public_profile_url": str(c.get("public_profile_url", "")).strip()[:400],
        "email": str(c.get("email", "")).strip()[:160],
        "email_status": status if status in _EMAIL_STATUS else "none",
        "email_note": str(c.get("email_note", "")).strip()[:300],
        "source": str(c.get("source", "")).strip()[:300],
    }


def find(company: str, role: str = "", tracked_id: int | None = None, force: bool = False) -> dict:
    company = (company or "").strip()
    if not company:
        return {"ok": False, "error": "company is required"}
    with get_conn() as conn:
        if not force:
            row = conn.execute("SELECT * FROM referrals WHERE company=?", (company,)).fetchone()
            if row and row["contacts_json"]:
                return {"ok": True, "company": company, "role": row["role"] or role,
                        "contacts": json.loads(row["contacts_json"]), "cached": True}

    prompt = (
        f"Company: {company}\n"
        f"Role I'm interested in: {role or 'software / backend engineering'}\n\n"
        "Identify the best person (or few) to ask for a referral, following the rules exactly. "
        "Return the JSON array."
    )
    try:
        raw = client.complete_with_web_search(prompt, system=_FIND_SYSTEM, tier="fast", max_tokens=2500)
        parsed = client._parse_json(raw) if raw.strip() else []
    except Exception as e:  # noqa: BLE001
        with get_conn() as conn:
            log_run(conn, AGENT, f"company={company}", validation_passed=False, error_text=str(e))
        return {"ok": False, "error": str(e)}

    contacts = [_clean_contact(c) for c in parsed if isinstance(c, dict) and c.get("name")] \
        if isinstance(parsed, list) else []
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO referrals (tracked_id, company, role, contacts_json, computed_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(company) DO UPDATE SET
                 tracked_id=COALESCE(excluded.tracked_id, referrals.tracked_id),
                 role=excluded.role, contacts_json=excluded.contacts_json,
                 computed_at=excluded.computed_at""",
            (tracked_id, company, role, json.dumps(contacts), now_iso()))
        log_run(conn, AGENT, f"company={company}", output_ref=f"contacts={len(contacts)}")
    return {"ok": True, "company": company, "role": role, "contacts": contacts, "cached": False}


def draft(company: str, contact: dict, role: str = "", tracked_id: int | None = None) -> dict:
    """Draft a referral-request email to `contact` (a dict from find()). Never sends. If Gmail is
    connected and the contact has an email, also creates a Gmail draft the user can review/send."""
    from backend.agents.cover_letter import clean_text
    from backend.integrations import gmail

    company = (company or "").strip()
    if not company or not isinstance(contact, dict) or not contact.get("name"):
        return {"ok": False, "error": "company and a contact are required"}

    p = profile.get()
    recipient = f"{contact.get('name')} ({contact.get('title','')})".strip()
    out = client.complete_json(
        f"Recipient: {recipient} at {company}.\n"
        f"Why them: {contact.get('why_them','')}\n"
        f"Role I want a referral for: {role or 'software / backend engineering'}\n\n"
        f"About me: {p['profile_summary']}\n"
        f"LinkedIn: {p['linkedin']} · GitHub: {p['github']}\n\n"
        "Write the referral-request email.",
        system=_draft_system(p["name"]), tier="smart", max_tokens=700,
    )
    subject = clean_text(out.get("subject", "") if isinstance(out, dict) else "")
    body = clean_text(out.get("body", "") if isinstance(out, dict) else str(out))

    to = contact.get("email") if contact.get("email_status") == "found" else ""
    gmail_draft_id, note = None, ""
    if not to and contact.get("email"):
        note = "The recipient's email is inferred, not confirmed — verify it before sending."
    if to and gmail.is_connected():
        try:
            gmail_draft_id = gmail.create_draft(to, subject, body)
        except Exception as e:  # noqa: BLE001
            note = f"Gmail draft not created ({e}); the text is saved to copy/send manually."
    elif to:
        note = "Gmail not connected — email text saved; connect Gmail to auto-create drafts."

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO referrals (tracked_id, company, role, draft_to, draft_subject,
                 draft_body, gmail_draft_id, computed_at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(company) DO UPDATE SET
                 draft_to=excluded.draft_to, draft_subject=excluded.draft_subject,
                 draft_body=excluded.draft_body, gmail_draft_id=excluded.gmail_draft_id""",
            (tracked_id, company, role, contact.get("email") or contact.get("name"),
             subject, body, gmail_draft_id, now_iso()))
        log_run(conn, AGENT, f"company={company}", output_ref=f"draft_to={to or 'manual'}")
    return {"ok": True, "company": company, "to": to or contact.get("email") or "",
            "email_status": contact.get("email_status", "none"), "subject": subject, "body": body,
            "gmail_draft_id": gmail_draft_id,
            "gmail_draft_url": gmail.draft_url(gmail_draft_id) if gmail_draft_id else None,
            "note": note}


def get(company: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM referrals WHERE company=?", ((company or "").strip(),)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["contacts"] = json.loads(d["contacts_json"]) if d.get("contacts_json") else []
    return d
