"""Cover-letter generation.

Writes a concise, specific cover letter for a job, grounded in the candidate's real résumé
and the JD. Same honesty guardrail as the rest of the tool: every claim must trace to the
résumé — it never invents experience. Draft-only; the user reviews, edits, and sends it.
"""
from __future__ import annotations

from backend.db.database import get_conn, log_run, now_iso
from backend.llm import client
from backend.resume import latex

AGENT = "cover_letter"
TRACK_MAP = {"go": "go", "node": "node", "ambiguous": "go", "other": "go"}

def _system() -> str:
    from backend import profile
    p = profile.get()
    return (
        f"You write a concise, genuine cover letter for {p['name']} "
        f"({p['profile_summary']}) applying to a specific role. "
        "HARD RULE: ground every claim in the candidate's résumé — never invent experience, "
        "skills, employers, or metrics. Reference the specific company and role and give concrete, "
        "résumé-backed reasons the candidate is a strong fit. Professional and warm, not templated; "
        "no clichés like 'I am writing to express my interest'. 220-320 words, plain text, "
        f"signed as {p['name']}. "
        "Return JSON {subject: <email subject line>, body: <the letter, plain text with paragraphs>}."
    )


def _track(job: dict) -> str:
    return TRACK_MAP.get(job.get("stack_guess") or "ambiguous", "go")


# Models love fancy Unicode punctuation (em-dashes, curly quotes) which turns into garbage
# in plain-text ATS boxes. Normalize to clean ASCII.
_PUNCT = {
    "—": " - ", "–": "-", "‘": "'", "’": "'", "“": '"',
    "”": '"', "…": "...", " ": " ", "‑": "-", "•": "-",
}


def clean_text(s: str) -> str:
    for bad, good in _PUNCT.items():
        s = (s or "").replace(bad, good)
    return s


def generate(job_id: int, force: bool = False) -> dict:
    with get_conn() as conn:
        if not force:
            cached = conn.execute("SELECT * FROM cover_letters WHERE job_id=?", (job_id,)).fetchone()
            if cached:
                d = dict(cached); d["cached"] = True; return d
        job = conn.execute(
            """SELECT j.*, co.name AS company FROM jobs j JOIN companies co ON co.id=j.company_id
               WHERE j.id=?""", (job_id,)).fetchone()
    if not job:
        return {"ok": False, "error": "job not found"}
    job = dict(job)
    resume = latex.base_resume_text(_track(job))
    out = client.complete_json(
        f"COMPANY: {job['company']}\nROLE: {job['title']}\n\n"
        f"JOB DESCRIPTION:\n{(job.get('jd_text') or '')[:9000]}\n\n"
        f"CANDIDATE RÉSUMÉ:\n{resume[:9000]}",
        system=_system(), tier="smart", max_tokens=1200,
    )
    subject = clean_text(out.get("subject", "") if isinstance(out, dict) else "")
    body = clean_text(out.get("body", "") if isinstance(out, dict) else str(out))
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO cover_letters (job_id, subject, body, status, created_at)
               VALUES (?,?,?, 'draft', ?)
               ON CONFLICT(job_id) DO UPDATE SET subject=excluded.subject, body=excluded.body,
                 status='draft', created_at=excluded.created_at""",
            (job_id, subject, body, now_iso()),
        )
        log_run(conn, AGENT, f"job={job_id}", output_ref=f"chars={len(body)}")
    return {"ok": True, "job_id": job_id, "subject": subject, "body": body, "cached": False}


def get(job_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cover_letters WHERE job_id=?", (job_id,)).fetchone()
    return dict(row) if row else None


def save(job_id: int, subject: str, body: str) -> dict:
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO cover_letters (job_id, subject, body, status, created_at)
               VALUES (?,?,?, 'edited', ?)
               ON CONFLICT(job_id) DO UPDATE SET subject=excluded.subject, body=excluded.body,
                 status='edited', created_at=excluded.created_at""",
            (job_id, subject, body, now_iso()),
        )
    return {"ok": True, "job_id": job_id, "status": "edited"}
