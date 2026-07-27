"""Local FastAPI layer the Next.js dashboard talks to.

Runs on 127.0.0.1 only (single local user). Exposes read endpoints for each dashboard
page and the human-checkpoint actions (approve/reject resume diffs, launch apply, mark
applied, save screening answers, verify contacts, add company). It NEVER exposes an
endpoint that submits an application or sends an email.

Run:  uvicorn backend.api.main:app --host 127.0.0.1 --port 8010
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import config
from backend.agents import (application_submission, contact_discovery, daily_reporter,
                            outreach_composer, resume_tailor, screening)
from backend.db.database import get_conn, init_db
from backend.db.seed import add_company
from backend.integrations import gmail


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Ensure the schema exists and is up to date before serving. init_db() is idempotent
    # (CREATE TABLE IF NOT EXISTS + additive migrations), so pulling new features and
    # restarting the API is enough — no manual migration step, no "no such table" errors.
    init_db()
    yield


app = FastAPI(title="Job Application Agent — Local API", lifespan=_lifespan)
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


@app.get("/api/insights")
def insights():
    from backend.agents import insights as ins
    return ins.compute()


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


class ManualApp(BaseModel):
    company: str
    role: str = ""
    platform: str = "direct"
    status: str = "applied"
    applied_on: Optional[str] = None
    note: str = ""


@app.post("/api/tracker/manual")
def tracker_add_manual(body: ManualApp):
    """Add an application that never appeared in Gmail (offline / phone-only)."""
    from backend.agents import application_tracker
    return application_tracker.add_manual(
        company=body.company, role=body.role, platform=body.platform,
        status=body.status, applied_on=body.applied_on, note=body.note)


class ManualEvent(BaseModel):
    note: str = ""
    status: Optional[str] = None
    on_date: Optional[str] = None


@app.post("/api/tracker/{tracked_id}/event")
def tracker_add_event(tracked_id: int, body: ManualEvent):
    """Log a hand-entered update on an application (HR called, LinkedIn message, etc.)."""
    from backend.agents import application_tracker
    return application_tracker.add_event(
        tracked_id, note=body.note, status=body.status, on_date=body.on_date)


@app.get("/api/gmail/status")
def gmail_status():
    """Gmail is optional. `connected` = consent completed (token cached); `credentials` =
    an OAuth client secret is present so the Connect button can run the consent flow."""
    return {"connected": gmail.is_connected(),
            "credentials": config.GMAIL_CREDENTIALS_JSON.exists()}


@app.post("/api/gmail/connect")
def gmail_connect():
    """Run the one-time OAuth consent (opens a browser). Requires credentials.json."""
    return gmail.connect()


# ---------------- Resume library ----------------

@app.post("/api/resumes/upload")
async def resumes_upload(track: str = Form(...), label: str = Form(""),
                         tex: Optional[UploadFile] = File(None),
                         pdf: Optional[UploadFile] = File(None)):
    """Upload a base resume (LaTeX .tex and/or .pdf) for a track; becomes the active one."""
    from backend.resume import store
    if track not in ("go", "node"):
        raise HTTPException(400, "track must be 'go' or 'node'")
    tex_content = (await tex.read()).decode("utf-8", "ignore") if tex else None
    pdf_bytes = await pdf.read() if pdf else None
    if not tex_content and not pdf_bytes:
        raise HTTPException(400, "provide a .tex and/or .pdf file")
    filename = (tex.filename if tex else "") or (pdf.filename if pdf else "")
    return store.save_base_resume(track, tex_content, pdf_bytes, filename, label)


@app.get("/api/resumes/base")
def resumes_base():
    from backend.resume import store
    return store.list_base_resumes()


@app.get("/api/resumes/tailored")
def resumes_tailored():
    """Jobs that have a tailored resume, for the per-JD resume viewer."""
    return _rows(
        """SELECT j.id AS job_id, j.title, j.stack_guess, co.name AS company,
                  r.base_track, r.hitl_status,
                  (r.tex_content IS NOT NULL AND r.tex_content!='') AS has_tailored
           FROM resumes r JOIN jobs j ON j.id=r.job_id JOIN companies co ON co.id=j.company_id
           ORDER BY r.id DESC""")


@app.get("/api/resumes/job/{job_id}")
def resume_for_job(job_id: int):
    """Original (base) vs tailored resume for a job, for side-by-side viewing."""
    from backend.resume import latex, store
    with get_conn() as c:
        job = c.execute("""SELECT j.title, j.stack_guess, co.name AS company
                           FROM jobs j JOIN companies co ON co.id=j.company_id
                           WHERE j.id=?""", (job_id,)).fetchone()
        r = c.execute("""SELECT id, base_track, diff_json, tex_content, hitl_status, final_pdf_path
                         FROM resumes WHERE job_id=? ORDER BY id DESC LIMIT 1""", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "job not found")
    track = (dict(r)["base_track"] if r else None) or "go"
    return {
        "job": dict(job),
        "track": track,
        "base_tex": latex.base_tex_source(track) or "",
        "has_uploaded_base": store.get_base_tex(track) is not None,
        "tailored_tex": (dict(r).get("tex_content") if r else None) or "",
        "diff": json.loads(dict(r).get("diff_json") or "{}") if r else {},
        "hitl_status": dict(r).get("hitl_status") if r else None,
    }


# ---------------- Résumé ↔ JD match ----------------

@app.get("/api/match")
def match_list(limit: int = 100):
    """Analyzed jobs ranked by fit — the AI score if computed, else an instant heuristic."""
    from backend.agents import resume_match
    return resume_match.rank(limit)


@app.post("/api/match/score-batch")
def match_score_batch(limit: int = 20):
    """AI-score the top unscored jobs (by heuristic), so the ranking sharpens."""
    from backend.agents import resume_match
    return resume_match.score_batch(limit)


@app.get("/api/match/{job_id}")
def match_score(job_id: int, force: bool = False):
    from backend.agents import resume_match
    return resume_match.score(job_id, force=force)


class OptimizeReq(BaseModel):
    keywords: Optional[list[str]] = None


@app.post("/api/match/{job_id}/optimize")
def match_optimize(job_id: int, body: OptimizeReq):
    from backend.agents import resume_match
    return resume_match.optimize(job_id, body.keywords)


# ---------------- Cover letters ----------------

@app.get("/api/cover-letter/{job_id}")
def cover_letter_get(job_id: int):
    from backend.agents import cover_letter
    return cover_letter.get(job_id) or {"job_id": job_id, "body": "", "subject": ""}


@app.post("/api/cover-letter/{job_id}/generate")
def cover_letter_generate(job_id: int, force: bool = False):
    from backend.agents import cover_letter
    return cover_letter.generate(job_id, force=force)


class CoverLetterSave(BaseModel):
    subject: str = ""
    body: str = ""


@app.post("/api/cover-letter/{job_id}/save")
def cover_letter_save(job_id: int, body: CoverLetterSave):
    from backend.agents import cover_letter
    return cover_letter.save(job_id, body.subject, body.body)


# ---------------- Reminders / next actions ----------------

@app.get("/api/reminders")
def reminders():
    from backend.agents import reminders as rem
    return rem.next_actions()


@app.post("/api/reminders/{tracked_id}/followup")
def reminders_followup(tracked_id: int):
    from backend.agents import reminders as rem
    return rem.followup_draft(tracked_id)


# ---------------- Referrals ----------------

class ReferralFind(BaseModel):
    company: str
    role: str = ""
    tracked_id: Optional[int] = None
    force: bool = False


@app.post("/api/referrals/find")
def referrals_find(body: ReferralFind):
    from backend.agents import referral_finder
    return referral_finder.find(body.company, role=body.role,
                                tracked_id=body.tracked_id, force=body.force)


class ReferralDraft(BaseModel):
    company: str
    contact: dict
    role: str = ""
    tracked_id: Optional[int] = None


@app.post("/api/referrals/draft")
def referrals_draft(body: ReferralDraft):
    from backend.agents import referral_finder
    return referral_finder.draft(body.company, body.contact,
                                 role=body.role, tracked_id=body.tracked_id)


@app.get("/api/referrals")
def referrals_get(company: str):
    from backend.agents import referral_finder
    return referral_finder.get(company) or {"company": company, "contacts": []}


# ---------------- Interview prep ----------------

@app.get("/api/interview-prep")
def interview_prep_list():
    from backend.agents import interview_prep
    return interview_prep.list_interviews()


@app.get("/api/interview-prep/{tracked_id}")
def interview_prep_get(tracked_id: int):
    from backend.agents import interview_prep
    return interview_prep.get(tracked_id) or {"tracked_id": tracked_id, "prep": {}}


@app.post("/api/interview-prep/{tracked_id}/generate")
def interview_prep_generate(tracked_id: int, force: bool = False):
    from backend.agents import interview_prep
    return interview_prep.generate(tracked_id, force=force)


# ---------------- Profile / onboarding ----------------

class ProfileSave(BaseModel):
    name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    linkedin: str = ""
    github: str = ""
    location: str = ""
    profile_summary: str = ""
    keyword_filters: str = ""
    location_filters: str = ""


@app.get("/api/profile")
def profile_get():
    from backend import profile
    return {"profile": profile.get(), "is_set": profile.is_set()}


@app.post("/api/profile")
def profile_save(body: ProfileSave):
    from backend import profile
    return profile.save(body.model_dump())


@app.get("/api/health")
def health():
    return {"ok": True, "db": str(config.DB_PATH)}
