"""Local FastAPI layer the Next.js dashboard talks to.

Runs on 127.0.0.1 only (single local user). Exposes read endpoints for each dashboard
page and the human-checkpoint actions (approve/reject resume diffs, launch apply, mark
applied, save screening answers, verify contacts, add company). It NEVER exposes an
endpoint that submits an application or sends an email.

Run:  uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import config
from backend.agents import (application_submission, contact_discovery, daily_reporter,
                            outreach_composer, resume_tailor, screening)
from backend.db.database import get_conn
from backend.db.seed import add_company
from backend.integrations import gmail

app = FastAPI(title="Job Application Agent — Local API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"], allow_headers=["*"],
)


def _rows(query: str, *params) -> list[dict]:
    with get_conn() as c:
        return [dict(r) for r in c.execute(query, params).fetchall()]


# ---------------- 1. Diff Approval queue ----------------

@app.get("/api/diffs")
def list_diffs():
    rows = _rows(
        """SELECT r.id AS resume_id, r.base_track, r.diff_json, r.hitl_status,
                  j.id AS job_id, j.title, j.stack_guess, j.jd_url, co.name AS company
           FROM resumes r JOIN jobs j ON j.id=r.job_id JOIN companies co ON co.id=j.company_id
           WHERE r.hitl_status='pending' ORDER BY r.id DESC""")
    for r in rows:
        r["diff"] = json.loads(r.pop("diff_json") or "{}")
    return rows


class DiffDecision(BaseModel):
    action: str  # approve | edit | reject
    edited_diff: Optional[dict] = None


@app.post("/api/diffs/{resume_id}/decision")
def decide_diff(resume_id: int, body: DiffDecision):
    if body.action == "reject":
        return resume_tailor.reject(resume_id)
    if body.action in ("approve", "edit"):
        return resume_tailor.finalize(resume_id, body.edited_diff if body.action == "edit" else None)
    raise HTTPException(400, "action must be approve|edit|reject")


# ---------------- 2. Apply Queue ----------------

@app.get("/api/apply-queue")
def apply_queue():
    return _rows(
        """SELECT j.id AS job_id, j.title, j.jd_url, j.source, j.stack_guess, j.status,
                  co.name AS company, r.id AS resume_id, r.base_track, r.final_pdf_path
           FROM jobs j JOIN resumes r ON r.job_id=j.id JOIN companies co ON co.id=j.company_id
           WHERE j.status IN ('ready_to_apply','flagged') AND r.hitl_status IN ('approved','edited')
           ORDER BY j.id DESC""")


@app.post("/api/apply-queue/{job_id}/launch")
def launch_apply(job_id: int):
    """Launch the HEADED Playwright session for this job (blocks until the browser
    is closed). The human clicks submit; this never submits."""
    return application_submission.launch(job_id)


class MarkApplied(BaseModel):
    ats_confirmation_ref: str = ""


@app.post("/api/apply-queue/{job_id}/mark-applied")
def mark_applied(job_id: int, body: MarkApplied):
    res = application_submission.mark_applied(job_id, body.ats_confirmation_ref)
    # Kick off contact discovery + outreach automatically for the new application.
    try:
        contact_discovery.discover_for_application(res["application_id"])
    except Exception:  # noqa: BLE001
        pass
    return res


# ---------------- 3. Screening Q&A gaps ----------------

@app.get("/api/screening-gaps")
def screening_gaps():
    with get_conn() as c:
        return screening.open_gaps(c)


class ScreeningAnswer(BaseModel):
    question_key: str
    question_text: Optional[str] = None
    answer_go: str = ""
    answer_node: str = ""


@app.post("/api/screening-gaps/save")
def save_screening(body: ScreeningAnswer):
    return screening.save_answer(body.question_key, body.answer_go, body.answer_node, body.question_text)


# ---------------- 4. Outreach queue ----------------

@app.get("/api/outreach")
def outreach():
    rows = _rows(
        """SELECT d.id, d.contact_id, d.application_id, d.channel, d.draft_text, d.subject_line,
                  d.gmail_draft_id, d.status, ct.name AS contact_name, ct.role_guess,
                  ct.public_profile_url, ct.verified_by_human, co.name AS company, j.title
           FROM outreach_drafts d JOIN contacts ct ON ct.id=d.contact_id
           JOIN companies co ON co.id=ct.company_id
           JOIN applications a ON a.id=d.application_id JOIN jobs j ON j.id=a.job_id
           ORDER BY d.created_at DESC""")
    for r in rows:
        r["gmail_draft_url"] = gmail.draft_url(r["gmail_draft_id"]) if r["gmail_draft_id"] else None
    return rows


@app.get("/api/contacts")
def contacts():
    """Unverified candidate contacts awaiting human confirmation before drafting."""
    return _rows(
        """SELECT ct.*, co.name AS company FROM contacts ct JOIN companies co ON co.id=ct.company_id
           ORDER BY ct.verified_by_human ASC, ct.id DESC""")


class VerifyContact(BaseModel):
    verified: bool = True


@app.post("/api/contacts/{contact_id}/verify")
def verify_contact(contact_id: int, body: VerifyContact):
    res = contact_discovery.verify_contact(contact_id, body.verified)
    if body.verified:  # draft outreach immediately upon confirmation
        try:
            outreach_composer.compose_for_contact(contact_id)
        except Exception:  # noqa: BLE001
            pass
    return res


# ---------------- 5. Add company ----------------

class NewCompany(BaseModel):
    name: str
    careers_url: str = ""


@app.post("/api/companies/add")
def companies_add(body: NewCompany):
    return add_company(body.name, body.careers_url, verify=True)


@app.get("/api/companies")
def companies():
    return _rows("SELECT * FROM companies ORDER BY name")


class ScoutArea(BaseModel):
    area: str
    extra_keywords: str = ""


@app.post("/api/companies/scout")
def companies_scout(body: ScoutArea):
    """Find companies actively hiring in an area (via web search) and add them with ATS
    auto-detection, so Job Discovery starts polling the pollable ones."""
    from backend.agents import area_scout
    return area_scout.scout_and_add(body.area, body.extra_keywords)


@app.post("/api/companies/{company_id}/read-careers")
def companies_read_careers(company_id: int):
    """Read an employer's own careers page (headless browser + LLM) and insert its jobs.
    For 'unverified' companies with no public ATS API. Needs careers_url on the company."""
    from backend.agents import career_reader
    return career_reader.scout_company(company_id)


# ---------------- 6. Daily digest ----------------

@app.get("/api/digest")
def digest():
    return daily_reporter.summary()


# ---------------- 7. Application tracker (from Gmail) ----------------

@app.get("/api/tracker")
def tracker():
    from backend.agents import application_tracker
    return application_tracker.summary()


@app.post("/api/tracker/refresh")
def tracker_refresh():
    from backend.agents import application_tracker
    return application_tracker.run()


@app.get("/api/tracker/{tracked_id}")
def tracker_detail(tracked_id: int):
    from backend.agents import application_tracker
    return application_tracker.detail(tracked_id)


class TrackerUpdate(BaseModel):
    status: Optional[str] = None
    hidden: Optional[bool] = None


@app.post("/api/tracker/{tracked_id}/update")
def tracker_update(tracked_id: int, body: TrackerUpdate):
    from backend.agents import application_tracker
    return application_tracker.update_entry(tracked_id, status=body.status, hidden=body.hidden)


@app.get("/api/health")
def health():
    return {"ok": True, "db": str(config.DB_PATH)}
