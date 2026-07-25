"""Contact Discovery Agent.

Given a newly logged application's company, finds a relevant contact using PUBLIC
sources only — company team/about pages, GitHub org members, other public-facing
profile links surfaced via Claude's web_search tool. NO LinkedIn scraping.

It proposes candidate name(s) + public link(s) with verified_by_human=0; Tushar confirms
relevance in the dashboard before the Outreach Composer proceeds.
"""
from __future__ import annotations

import json

from backend import config
from backend.db.database import get_conn, log_run
from backend.llm import claude

AGENT = "contact_discovery"

_SYSTEM = (
    "You find likely-relevant hiring contacts for a job application using ONLY public web "
    "sources: the company's team/about/careers pages, GitHub org member pages, public "
    "engineering-blog author bylines, conference speaker pages. Do NOT use or scrape LinkedIn. "
    "Prefer engineering managers, tech leads, or recruiters for the relevant team. "
    "Return JSON array (max 3) of {name, role_guess, public_profile_url, source, rationale}. "
    "Only include contacts you found on a real public page with a working URL. If none, return []."
)


def discover_for_application(application_id: int) -> dict:
    with get_conn() as conn:
        app = conn.execute(
            """SELECT a.id, a.job_id, j.company_id, j.title, c.name AS company, c.ats_slug
               FROM applications a JOIN jobs j ON j.id=a.job_id
               JOIN companies c ON c.id=j.company_id WHERE a.id=?""", (application_id,)).fetchone()
        if not app:
            return {"ok": False, "error": "application not found"}
        app = dict(app)
        # Skip if we already have candidates for this company.
        existing = conn.execute("SELECT COUNT(*) n FROM contacts WHERE company_id=?",
                                (app["company_id"],)).fetchone()["n"]
        if existing:
            return {"ok": True, "company": app["company"], "skipped": "already has contacts"}

    prompt = (
        f"Company: {app['company']}\nRole applied to: {app['title']}\n"
        f"GitHub org slug guess: {app.get('ats_slug') or 'unknown'}\n\n"
        "Find up to 3 public, relevant hiring contacts (eng manager / tech lead / recruiter "
        "for backend or AI teams). Return the JSON array described in the system prompt."
    )
    try:
        raw = claude.complete_with_web_search(prompt, system=_SYSTEM,
                                              tier="fast", max_tokens=2000)
        candidates = claude._parse_json(raw) if raw.strip() else []
    except Exception as e:  # noqa: BLE001
        with get_conn() as conn:
            log_run(conn, AGENT, f"app={application_id}", validation_passed=False, error_text=str(e))
        return {"ok": False, "error": str(e)}

    inserted = 0
    with get_conn() as conn:
        for c in candidates if isinstance(candidates, list) else []:
            if not c.get("name") or not c.get("public_profile_url"):
                continue
            conn.execute(
                """INSERT INTO contacts
                   (company_id, name, role_guess, public_profile_url, source, verified_by_human)
                   VALUES (?,?,?,?,?, 0)""",
                (app["company_id"], c["name"], c.get("role_guess", ""),
                 c["public_profile_url"], c.get("source", "web_search")),
            )
            inserted += 1
        log_run(conn, AGENT, f"app={application_id}", output_ref=f"candidates={inserted}")

    return {"ok": True, "company": app["company"], "candidates": inserted}


def run() -> dict:
    """Discover contacts for every applied job whose company has no contacts yet."""
    processed = 0
    with get_conn() as conn:
        apps = [dict(r) for r in conn.execute(
            """SELECT a.id FROM applications a JOIN jobs j ON j.id=a.job_id
               WHERE NOT EXISTS (SELECT 1 FROM contacts c WHERE c.company_id=j.company_id)"""
        ).fetchall()]
    for a in apps:
        discover_for_application(a["id"])
        processed += 1
    return {"agent": AGENT, "ok": True, "processed": processed}


def verify_contact(contact_id: int, verified: bool = True) -> dict:
    """Dashboard action: Tushar confirms a contact is relevant before outreach drafting."""
    with get_conn() as conn:
        conn.execute("UPDATE contacts SET verified_by_human=? WHERE id=?",
                     (1 if verified else 0, contact_id))
    return {"ok": True, "contact_id": contact_id, "verified": verified}
