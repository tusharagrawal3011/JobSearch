"""Reminders / next-actions — makes the tracker active, not passive.

For every tracked application it computes the single most useful next action (follow up,
complete an assessment, confirm/prepare an interview, respond to an offer), bucketed by
urgency. It can also draft a short, polite follow-up email (draft-only) for stalled
applications — as a Gmail draft to the last recruiter if Gmail is connected, else as text
you copy. No email is ever sent automatically.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from backend import config
from backend.db.database import get_conn, now_iso
from backend.llm import client

AGENT = "reminders"

# urgency: "now" (do today) · "soon" (this week) · "waiting"
TERMINAL = {"rejected", "withdrawn", "offer"}


def _days_since(iso: str) -> int:
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - then).days)
    except Exception:  # noqa: BLE001
        return 0


def classify_action(status: str, days: int, needs_action: bool, action_hint: str = "") -> dict:
    """Pure rule: given an application's status + age, return the next action + urgency."""
    if status == "offer":
        return {"action": "Respond to the offer", "urgency": "now", "can_followup": False}
    if needs_action:   # tracker already flagged a pending assessment/interview step
        return {"action": action_hint or "Action needed", "urgency": "now", "can_followup": False}
    if status == "assessment":
        return {"action": "Complete the assessment", "urgency": "soon", "can_followup": False}
    if status == "interview":
        return {"action": "Prepare for / confirm the interview", "urgency": "soon", "can_followup": True}
    if status == "applied":
        if days >= 2 * config.FOLLOWUP_DAYS:
            return {"action": f"Follow up - {days} days, no response", "urgency": "now", "can_followup": True}
        if days >= config.FOLLOWUP_DAYS:
            return {"action": f"Follow up soon - {days} days, no response", "urgency": "soon", "can_followup": True}
        return {"action": f"Awaiting response - {days} days", "urgency": "waiting", "can_followup": False}
    return {"action": "Awaiting update", "urgency": "waiting", "can_followup": False}


def next_actions() -> dict:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tracked_applications WHERE hidden=0 AND status NOT IN ('rejected','withdrawn')"
        ).fetchall()
    items = []
    for r in rows:
        r = dict(r)
        days = _days_since(r.get("last_update") or r.get("first_seen") or now_iso())
        act = classify_action(r["status"], days, bool(r.get("needs_action")), r.get("action_hint") or "")
        items.append({
            "id": r["id"], "company": r["company"], "role": r["role"] or r["latest_subject"],
            "status": r["status"], "days": days, **act,
        })
    order = {"now": 0, "soon": 1, "waiting": 2}
    items.sort(key=lambda x: (order.get(x["urgency"], 3), -x["days"]))
    counts = {u: sum(1 for i in items if i["urgency"] == u) for u in ("now", "soon", "waiting")}
    return {"items": items, "counts": counts, "followup_days": config.FOLLOWUP_DAYS}


def _last_sender_email(conn, tracked_id: int) -> str | None:
    from backend import profile
    row = conn.execute(
        """SELECT sender FROM tracked_events WHERE tracked_id=? AND sender NOT LIKE ?
           ORDER BY ts DESC LIMIT 1""", (tracked_id, f"%{profile.get()['email']}%")).fetchone()
    if not row:
        return None
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", row["sender"] or "")
    return m.group(0) if m else None


def _system() -> str:
    from backend import profile
    name = profile.get()["name"]
    return (
        f"You write a very short, polite follow-up email for {name}, checking in on a "
        "job application with no recent response. Warm, brief (60-110 words), not pushy, reaffirm "
        "genuine interest, invite next steps. Return JSON {subject, body}. Sign as "
        f"{name}. No clichés, no exaggeration."
    )


def followup_draft(tracked_id: int) -> dict:
    from backend.agents.cover_letter import clean_text
    from backend.integrations import gmail

    with get_conn() as conn:
        app = conn.execute("SELECT * FROM tracked_applications WHERE id=?", (tracked_id,)).fetchone()
        if not app:
            return {"ok": False, "error": "application not found"}
        app = dict(app)
        to = _last_sender_email(conn, tracked_id)

    out = client.complete_json(
        f"Company: {app['company']}\nRole applied to: {app['role'] or app['latest_subject']}\n"
        f"Applied around {app.get('first_seen','')[:10]}, no recent response.",
        system=_system(), tier="smart", max_tokens=500,
    )
    subject = clean_text(out.get("subject", "") if isinstance(out, dict) else "")
    body = clean_text(out.get("body", "") if isinstance(out, dict) else str(out))

    gmail_draft_id, note = None, ""
    if gmail.is_connected() and to:
        try:
            gmail_draft_id = gmail.create_draft(to, subject, body)
        except Exception as e:  # noqa: BLE001
            note = f"Gmail draft not created ({e})."
    elif not gmail.is_connected():
        note = "Connect Gmail to auto-create the draft; text is ready to copy."
    elif not to:
        note = "No recruiter email on record — copy the text and send it yourself."

    return {"ok": True, "to": to, "subject": subject, "body": body,
            "gmail_draft_id": gmail_draft_id,
            "gmail_draft_url": gmail.draft_url(gmail_draft_id) if gmail_draft_id else None,
            "note": note}
