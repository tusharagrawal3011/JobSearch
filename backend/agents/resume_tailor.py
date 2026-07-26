"""Resume Tailor Agent.

Claude (Opus) proposes a DIFF ONLY against the matching base resume (go/node). It may
only touch: the one-line Professional Summary, the Technical Skills list, and bullet
ordering/emphasis within Experience & Projects. It must never invent experience/projects
or change dates, company names, contact info, education, or the Astrotech Labs internship.

Flow:
  propose()  -> writes a resumes row with hitl_status='pending' (the HITL checkpoint).
  Human approves/edits/rejects via the dashboard.
  finalize() -> on approval, renders the tailored resume through the LaTeX pipeline.
"""
from __future__ import annotations

import json

from backend import config
from backend.db.database import get_conn, log_run, now_iso
from backend.llm import claude
from backend.resume import latex

AGENT = "resume_tailor"

# stack_guess -> base track. 'other' is skipped (neither backend track fits).
TRACK_MAP = {"go": "go", "node": "node", "ambiguous": "go"}

_SYSTEM = (
    "You tailor a base resume to a specific job by proposing a DIFF ONLY — never a full "
    "rewrite. HARD CONSTRAINTS: you may only change (1) the one-line Professional Summary, "
    "(2) the Technical Skills list (reorder/emphasize existing skills; do not fabricate new "
    "technologies the candidate lacks), and (3) the ORDER and EMPHASIS of existing bullets in "
    "Experience & Projects. You must NEVER invent new experience or projects, never change "
    "dates or company names, and never touch contact info, education, or the Astrotech Labs "
    "internship bullets. "
    "Return JSON: {professional_summary:{before,after}, technical_skills:{before,after}, "
    "reordered_bullets:[{section,rationale,new_order:[bullet snippets in new order]}], "
    "notes:string}. Keep 'after' values grounded strictly in the base resume content."
)


def _base_track(stack_guess: str) -> str | None:
    return TRACK_MAP.get(stack_guess)  # None for 'other'


def propose(conn, job: dict) -> dict:
    track = _base_track(job.get("stack_guess") or "ambiguous")
    if track is None:
        conn.execute("UPDATE jobs SET status='skipped', flag_reason='stack=other' WHERE id=?", (job["id"],))
        log_run(conn, AGENT, f"job={job['id']}", output_ref="skipped(other)")
        return {"job_id": job["id"], "status": "skipped"}

    base_text = latex.base_resume_text(track)
    diff = claude.complete_json(
        f"BASE RESUME ({track} track):\n{base_text[:14000]}\n\n"
        f"TARGET JOB: {job['title']} @ company_id={job['company_id']}\n"
        f"Stack: {job.get('stack_guess')}  Seniority: {job.get('seniority')}\n"
        f"Keywords: {job.get('keywords')}\n\nJD:\n{(job.get('jd_text') or '')[:9000]}",
        system=_SYSTEM, tier="smart", max_tokens=3000,
    )

    cur = conn.execute(
        """INSERT INTO resumes (job_id, base_track, diff_json, hitl_status)
           VALUES (?,?,?, 'pending')""",
        (job["id"], track, json.dumps(diff, ensure_ascii=False)),
    )
    conn.execute("UPDATE jobs SET status='tailoring' WHERE id=?", (job["id"],))
    log_run(conn, AGENT, f"job={job['id']}", output_ref=f"resume={cur.lastrowid} track={track}")
    return {"job_id": job["id"], "resume_id": cur.lastrowid, "track": track, "status": "pending"}


def run() -> dict:
    """Propose diffs for all analyzed jobs that don't yet have a resume row."""
    proposed, skipped = 0, 0
    with get_conn() as conn:
        jobs = [dict(r) for r in conn.execute(
            """SELECT j.* FROM jobs j
               WHERE j.status='analyzed'
               AND NOT EXISTS (SELECT 1 FROM resumes r WHERE r.job_id=j.id)""").fetchall()]
        for job in jobs:
            res = propose(conn, job)
            if res["status"] == "pending":
                proposed += 1
            else:
                skipped += 1
    return {"agent": AGENT, "ok": True, "proposed": proposed, "skipped": skipped}


# ---------------- HITL resolution (called from the dashboard) ----------------

def _apply_diff_to_tex(base_tex: str, diff: dict) -> str:
    """Best-effort textual application of the summary swap into the .tex source.
    Bullet reordering/skills edits are surfaced in the diff for human review; the
    approved .tex is what actually renders. If no reliable automated swap is possible,
    returns the base tex unchanged (human can edit the queued diff)."""
    tex = base_tex
    summ = diff.get("professional_summary") or {}
    if summ.get("before") and summ.get("after") and summ["before"] in tex:
        tex = tex.replace(summ["before"], summ["after"], 1)
    return tex


def finalize(resume_id: int, edited_diff: dict | None = None) -> dict:
    """Called when the human approves (optionally with edits). Renders the PDF."""
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
        if not row:
            return {"ok": False, "error": "resume not found"}
        row = dict(row)
        track = row["base_track"]
        diff = edited_diff if edited_diff is not None else json.loads(row["diff_json"] or "{}")

        base_tex = latex.base_tex_source(track)
        tailored_tex = _apply_diff_to_tex(base_tex, diff) if base_tex else None
        result = latex.render(row["job_id"], track, tailored_tex)

        status = "edited" if edited_diff is not None else "approved"
        conn.execute(
            """UPDATE resumes SET diff_json=?, tex_content=?, final_pdf_path=?, hitl_status=?, reviewed_at=? WHERE id=?""",
            (json.dumps(diff, ensure_ascii=False), tailored_tex, result.get("pdf_path"),
             status, now_iso(), resume_id),
        )
        conn.execute("UPDATE jobs SET status='ready_to_apply' WHERE id=?", (row["job_id"],))
        log_run(conn, AGENT, f"resume={resume_id}", output_ref=result.get("mode", ""),
                validation_passed=result.get("ok", False), error_text=result.get("note", ""))
    return {"ok": True, "resume_id": resume_id, "render": result, "status": status}


def reject(resume_id: int) -> dict:
    with get_conn() as conn:
        row = conn.execute("SELECT job_id FROM resumes WHERE id=?", (resume_id,)).fetchone()
        conn.execute("UPDATE resumes SET hitl_status='rejected', reviewed_at=? WHERE id=?",
                     (now_iso(), resume_id))
        if row:
            conn.execute("UPDATE jobs SET status='skipped', flag_reason='resume rejected' WHERE id=?",
                         (row["job_id"],))
    return {"ok": True, "resume_id": resume_id, "status": "rejected"}
