"""Interview prep — the highest-value moment.

When you've reached an interview, this generates a company research brief (from public web
sources), likely interview questions tuned to the role AND your résumé's gaps, talking points
drawn from your real experience, and smart questions to ask them. Grounded and honest — the
talking points come from your résumé, never invented.
"""
from __future__ import annotations

import json

from backend.db.database import get_conn, log_run, now_iso
from backend.llm import client
from backend.resume import latex

AGENT = "interview_prep"


def _track_from_role(role: str) -> str:
    low = (role or "").lower()
    return "node" if any(w in low for w in ("node", "javascript", "mern", "react", "full stack", "full-stack")) else "go"


def list_interviews() -> list[dict]:
    """Tracked applications at interview/assessment stage — candidates for prep."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT t.id, t.company, t.role, t.latest_subject, t.status,
                      (p.id IS NOT NULL) AS has_prep
               FROM tracked_applications t
               LEFT JOIN interview_prep p ON p.tracked_id=t.id
               WHERE t.hidden=0 AND t.status IN ('interview','assessment','offer')
               ORDER BY CASE t.status WHEN 'interview' THEN 0 WHEN 'assessment' THEN 1 ELSE 2 END,
                        t.last_update DESC""").fetchall()
    return [dict(r) for r in rows]


_BRIEF_SYSTEM = (
    "You research a company for a candidate about to interview there, using public web sources. "
    "Return a concise brief (~180 words, plain text) covering: what the company does and its main "
    "products; notable recent news (past ~year); their tech stack if publicly known; and any public "
    "signal on their interview process or engineering culture. Only state things you can find; if "
    "something is unknown, omit it."
)

_PREP_SYSTEM = (
    "You are an interview coach. Given the company, role, a research brief, and the candidate's "
    "résumé, produce focused interview prep. Return JSON: "
    "{technical_questions:[6 likely technical questions for THIS role], "
    "behavioral_questions:[5 behavioral questions], "
    "gap_questions:[questions the interviewer may probe based on GAPS between the résumé and the role], "
    "talking_points:[5 strengths from the résumé to emphasize — grounded in the résumé, not invented], "
    "questions_to_ask:[5 sharp questions the candidate should ask the interviewer]}. "
    "Be specific to the role and company, not generic."
)


def generate(tracked_id: int, force: bool = False) -> dict:
    with get_conn() as conn:
        if not force:
            cached = conn.execute("SELECT * FROM interview_prep WHERE tracked_id=?", (tracked_id,)).fetchone()
            if cached:
                d = dict(cached); d["prep"] = json.loads(d.pop("prep_json") or "{}"); d["cached"] = True
                return d
        app = conn.execute("SELECT * FROM tracked_applications WHERE id=?", (tracked_id,)).fetchone()
    if not app:
        return {"ok": False, "error": "application not found"}
    app = dict(app)
    company, role = app["company"], (app["role"] or app["latest_subject"] or "the role")
    resume = latex.base_resume_text(_track_from_role(role))

    try:
        brief = client.complete_with_web_search(
            f"Company: {company}\nRole I'm interviewing for: {role}\nWrite the research brief.",
            system=_BRIEF_SYSTEM, tier="fast", max_tokens=1200)
    except Exception:  # noqa: BLE001 — grounding needs a search-capable provider; degrade
        brief = ""

    prep = client.complete_json(
        f"Company: {company}\nRole: {role}\n\nRESEARCH BRIEF:\n{brief[:3000]}\n\n"
        f"CANDIDATE RÉSUMÉ:\n{resume[:9000]}",
        system=_PREP_SYSTEM, tier="smart", max_tokens=2500)

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO interview_prep (tracked_id, company, role, brief, prep_json, created_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(tracked_id) DO UPDATE SET company=excluded.company, role=excluded.role,
                 brief=excluded.brief, prep_json=excluded.prep_json, created_at=excluded.created_at""",
            (tracked_id, company, role, brief, json.dumps(prep, ensure_ascii=False), now_iso()),
        )
        log_run(conn, AGENT, f"tracked={tracked_id}", output_ref=company)
    return {"ok": True, "tracked_id": tracked_id, "company": company, "role": role,
            "brief": brief, "prep": prep, "cached": False}


def get(tracked_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM interview_prep WHERE tracked_id=?", (tracked_id,)).fetchone()
    if not row:
        return None
    d = dict(row); d["prep"] = json.loads(d.pop("prep_json") or "{}")
    return d
