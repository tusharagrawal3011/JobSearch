"""Daily Reporter.

End-of-day summary surfaced as a dashboard view: companies applied to, resumes used,
items pending approval (resume diffs, apply-queue items, outreach drafts, unanswered
screening questions), broken down by source channel (ats_api vs. the three alert sources).
"""
from __future__ import annotations

from backend.db.database import get_conn

AGENT = "daily_reporter"


def summary() -> dict:
    with get_conn() as conn:
        def scalar(q, *p):
            return conn.execute(q, p).fetchone()[0]

        by_source = {r["source"]: r["n"] for r in conn.execute(
            "SELECT source, COUNT(*) n FROM jobs GROUP BY source").fetchall()}

        applied_by_source = {r["source"]: r["n"] for r in conn.execute(
            """SELECT j.source, COUNT(*) n FROM applications a
               JOIN jobs j ON j.id=a.job_id GROUP BY j.source""").fetchall()}

        status_counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM jobs GROUP BY status").fetchall()}

        applied_companies = [dict(r) for r in conn.execute(
            """SELECT c.name AS company, j.title, j.source, a.applied_at, r.base_track
               FROM applications a JOIN jobs j ON j.id=a.job_id
               JOIN companies c ON c.id=j.company_id
               LEFT JOIN resumes r ON r.id=a.resume_id
               ORDER BY a.applied_at DESC LIMIT 50""").fetchall()]

        pending = {
            "resume_diffs": scalar("SELECT COUNT(*) FROM resumes WHERE hitl_status='pending'"),
            "apply_queue": scalar("SELECT COUNT(*) FROM jobs WHERE status='ready_to_apply'"),
            "outreach_drafts": scalar("SELECT COUNT(*) FROM outreach_drafts WHERE status='drafted'"),
            "unanswered_screening": scalar(
                """SELECT COUNT(*) FROM screening_answers
                   WHERE (answer_go IS NULL OR answer_go='') AND (answer_node IS NULL OR answer_node='')"""),
            "flagged_jobs": scalar("SELECT COUNT(*) FROM jobs WHERE status='flagged'"),
            "unverified_contacts": scalar("SELECT COUNT(*) FROM contacts WHERE verified_by_human=0"),
        }

        return {
            "generated_by": AGENT,
            "jobs_by_source": by_source,
            "applied_by_source": applied_by_source,
            "status_counts": status_counts,
            "applied_companies": applied_companies,
            "pending": pending,
        }
