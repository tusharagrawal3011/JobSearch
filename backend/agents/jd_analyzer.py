"""JD Analyzer & Stack Classifier.

Claude (Sonnet) classifies stack_guess (go/node/ambiguous/other), extracts keywords,
seniority, and a short requirement summary. Validates the discovery agent's output
first: a job with empty jd_text or missing jd_url/company_id is flagged (status
'flagged'), NOT analyzed. For alert-sourced jobs jd_text is often empty — those are
flagged with a reason so the Application agent's redirect-follow can fetch the JD later,
rather than guessing.
"""
from __future__ import annotations

from backend import config
from backend.db.database import get_conn, log_run, now_iso
from backend.llm import claude

AGENT = "jd_analyzer"

_SYSTEM = (
    "You are a technical recruiter analyzing a job description for a backend/agentic-AI "
    "engineer (Go and Node tracks). Return JSON with keys: "
    "stack_guess (one of 'go','node','ambiguous','other'), "
    "keywords (array of up to 12 lowercase tech keywords), "
    "seniority (e.g. 'SDE-II','SDE-III','Senior','Lead','unknown'), "
    "summary (2-3 sentence requirement summary). "
    "Use 'go' if Go/Golang is primary, 'node' if Node.js/JS/TS backend is primary, "
    "'ambiguous' if either fits, 'other' if neither backend track fits."
)


def _validate(job: dict) -> tuple[bool, str]:
    if not job.get("company_id"):
        return False, "missing company_id"
    if not (job.get("jd_url") or "").strip():
        return False, "missing jd_url"
    if not (job.get("jd_text") or "").strip():
        return False, "empty jd_text (alert-sourced or fetch failed) — needs JD fetch before analysis"
    return True, ""


def analyze_one(conn, job: dict) -> dict:
    ok, reason = _validate(job)
    if not ok:
        conn.execute("UPDATE jobs SET status='flagged', flag_reason=? WHERE id=?", (reason, job["id"]))
        log_run(conn, AGENT, f"job={job['id']}", validation_passed=False, error_text=reason)
        return {"job_id": job["id"], "status": "flagged", "reason": reason}

    result = claude.complete_json(
        f"Title: {job['title']}\nLocation: {job.get('location','')}\n\nJD:\n{job['jd_text'][:12000]}",
        system=_SYSTEM, tier="fast", max_tokens=1200,
    )
    keywords = ", ".join(result.get("keywords", []))[:500]
    conn.execute(
        """UPDATE jobs SET stack_guess=?, keywords=?, seniority=?, status='analyzed' WHERE id=?""",
        (result.get("stack_guess", "ambiguous"), keywords, result.get("seniority", "unknown"), job["id"]),
    )
    log_run(conn, AGENT, f"job={job['id']}", output_ref=result.get("stack_guess", "ambiguous"))
    return {"job_id": job["id"], "status": "analyzed", **result}


def run() -> dict:
    analyzed, flagged = 0, 0
    with get_conn() as conn:
        jobs = [dict(r) for r in conn.execute("SELECT * FROM jobs WHERE status='new'").fetchall()]
        for job in jobs:
            res = analyze_one(conn, job)
            if res["status"] == "analyzed":
                analyzed += 1
            else:
                flagged += 1
    return {"agent": AGENT, "ok": True, "analyzed": analyzed, "flagged": flagged}
