"""Email Alert Parser Agent.

Reads Tushar's OWN Gmail inbox for job-alert emails from Naukri/Indeed/Cutshort —
mail sent to him because he set up alerts on those portals himself. It never contacts
the portals' servers. Parses each alert into structured rows and inserts them into
`jobs` with the matching source, resolving company_id by name (creating a lightweight
unverified company if needed so the ATS detector can resolve it later).
"""
from __future__ import annotations

from backend import config
from backend.db.database import get_conn, log_run, now_iso, stable_id
from backend.integrations import gmail
from backend.llm import claude

AGENT = "email_parser"

_SYSTEM = (
    "You extract job postings from a job-alert email (Naukri/Indeed/Cutshort). "
    "Alert emails are messy HTML. Return a JSON array; one object per distinct job with keys: "
    "company (string), title (string), location (string), url (the direct listing/apply URL). "
    "Only include real job listings, not footer/marketing links. If none, return []."
)


# Ollama structured-output schema — forces the model to emit ALL jobs in an array,
# rather than collapsing to a single object (qwen2.5:7b's failure mode with plain json).
JOBS_SCHEMA = {
    "type": "object",
    "properties": {
        "jobs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "location": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["title", "url"],
            },
        }
    },
    "required": ["jobs"],
}


def _coerce_jobs(x):
    """Normalize the extraction to a list of job dicts, tolerating provider quirks:
      * {"jobs": [...]}      (Ollama structured output / wrapper objects)
      * [ {...}, ... ]        (bare array — Gemini/Anthropic via prompt)
      * a single {...} job    (small models collapsing the array)
    Raises on anything unusable so the client retries / fails over. Empty list is valid."""
    if isinstance(x, dict):
        if isinstance(x.get("jobs"), list):
            x = x["jobs"]
        elif x.get("title") or x.get("url"):
            x = [x]
        else:
            # first list-of-dicts value, if any
            lists = [v for v in x.values() if isinstance(v, list)]
            if lists:
                x = lists[0]
            else:
                raise ValueError("no job array found in object response")
    if not isinstance(x, list):
        raise ValueError(f"expected a JSON array, got {type(x).__name__}")
    if any(not isinstance(item, dict) for item in x):
        raise ValueError("array items must be objects with title/company/location/url")
    return x


def _sender_domain(sender: str) -> str:
    at = sender.rfind("@")
    dom = sender[at + 1:].strip().strip(">").lower() if at != -1 else ""
    for known in config.ALERT_SENDER_DOMAINS:
        if known in dom:
            return known
    return dom


def _resolve_company_id(conn, name: str) -> int:
    name = (name or "Unknown").strip()
    row = conn.execute("SELECT id FROM companies WHERE lower(name)=lower(?)", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        """INSERT INTO companies (name, ats_type, priority, notes, added_at)
           VALUES (?, 'unverified', 'medium', 'Auto-created from job alert email', ?)""",
        (name, now_iso()),
    )
    return cur.lastrowid


def run(window_hours: int | None = None) -> dict:
    """Parse recent alert emails into jobs. Returns a summary dict.
    Gmail is optional — if it isn't configured, this skips cleanly (no OAuth prompt)."""
    if not gmail.is_configured():
        return {"agent": AGENT, "ok": True, "skipped": "Gmail not connected", "inserted": 0}
    window = window_hours or config.EMAIL_ALERT_WINDOW_HOURS
    inserted, parsed_emails, errors = 0, 0, 0

    try:
        msg_ids = gmail.list_alert_messages(window, config.ALERT_SENDER_DOMAINS)
    except Exception as e:  # noqa: BLE001 — Gmail not configured yet, etc.
        with get_conn() as conn:
            log_run(conn, AGENT, f"window={window}h", validation_passed=False, error_text=str(e))
        return {"agent": AGENT, "ok": False, "error": str(e), "inserted": 0}

    with get_conn() as conn:
        for mid in msg_ids:
            try:
                msg = gmail.get_message(mid)
                source = config.ALERT_DOMAIN_TO_SOURCE.get(_sender_domain(msg["sender"]))
                if not source:
                    continue
                content = (msg["body_text"] or "")[:20000] or msg["body_html"][:20000]
                if not content.strip():
                    continue
                jobs = claude.complete_json(
                    f"Alert email subject: {msg['subject']}\n\nBody:\n{content}",
                    system=_SYSTEM, tier="fast", max_tokens=3000,
                    coerce=_coerce_jobs, json_schema=JOBS_SCHEMA,
                )
                parsed_emails += 1
                for j in jobs if isinstance(jobs, list) else []:
                    # Validate required fields before inserting.
                    if not j.get("title") or not j.get("url"):
                        continue
                    company_id = _resolve_company_id(conn, j.get("company", "Unknown"))
                    ext = f"{source}:{msg['id']}:{stable_id(j['url'])}"
                    try:
                        cur = conn.execute(
                            """INSERT OR IGNORE INTO jobs
                               (company_id, external_id, title, jd_text, jd_url, location,
                                discovered_at, source, status)
                               VALUES (?,?,?,?,?,?,?,?, 'new')""",
                            (company_id, ext, j["title"], "", j["url"],
                             j.get("location", ""), now_iso(), source),
                        )
                        inserted += cur.rowcount if cur.rowcount > 0 else 0
                    except Exception:  # noqa: BLE001
                        errors += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                log_run(conn, AGENT, f"msg={mid}", validation_passed=False, error_text=str(e))
        log_run(conn, AGENT, f"emails={parsed_emails}", output_ref=f"jobs_inserted={inserted}")

    return {"agent": AGENT, "ok": True, "emails_parsed": parsed_emails,
            "inserted": inserted, "errors": errors}
