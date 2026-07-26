"""Application Submission Agent — headed Playwright.

Opens a HEADED browser (same code path for Greenhouse/Lever/Ashby AND Workday), follows
any portal->employer-ATS redirect, fills every field it can (contact info, resume upload,
screening questions matched from the bank), records unmatched questions as gaps and flags
the job 'needs your input', and then STOPS at the review/submit screen.

Tushar clicks submit himself — ALWAYS, Workday included. This module never clicks a final
submit button. After he submits, he marks it done in the dashboard (mark_applied) which
logs the applications row.
"""
from __future__ import annotations

import re
import time
from typing import Optional

from backend import config
from backend.agents import screening
from backend.db.database import get_conn, log_run, now_iso

AGENT = "application_submission"

# Submit-button text we deliberately AVOID clicking (human-only action).
_SUBMIT_WORDS = re.compile(r"\b(submit application|submit|apply now|send application)\b", re.I)

# Portal domains whose "Apply" buttons usually redirect to the employer's real ATS.
_PORTAL_DOMAINS = ("naukri.com", "indeed.com", "cutshort.io")

# Form-field label -> profile key. Values are resolved from the effective profile (DB > .env)
# at fill time, so editing your profile in the UI takes effect immediately.
_CONTACT_MAP = {
    "first name": "first_name", "last name": "last_name", "full name": "name",
    "name": "name", "email": "email", "phone": "phone", "mobile": "phone",
    "linkedin": "linkedin", "github": "github", "location": "location", "city": "location",
}


def _contact_values() -> dict:
    from backend import profile
    p = profile.get()
    return {label: p.get(key, "") for label, key in _CONTACT_MAP.items()}


def _detect_provider(url: str) -> str:
    u = url.lower()
    if "greenhouse.io" in u or "grnh.se" in u:
        return "greenhouse"
    if "lever.co" in u:
        return "lever"
    if "ashbyhq.com" in u:
        return "ashby"
    if "myworkdayjobs.com" in u or "workday" in u:
        return "workday"
    return "unknown"


def _load_job(conn, job_id: int) -> Optional[dict]:
    row = conn.execute(
        """SELECT j.*, r.id AS resume_id, r.final_pdf_path, r.base_track, r.hitl_status
           FROM jobs j JOIN resumes r ON r.job_id=j.id
           WHERE j.id=? ORDER BY r.id DESC LIMIT 1""", (job_id,)).fetchone()
    return dict(row) if row else None


def launch(job_id: int, interactive: bool = True, headless: Optional[bool] = None) -> dict:
    """Open the browser on the application form and fill what it can.

    interactive=True (default): headed browser, kept open at the review screen until the
    human closes it / submits manually — NEVER auto-submits.
    interactive=False: headless, fills the form, records screening gaps, then closes and
    returns immediately (used for testing / CI). Still never submits.
    """
    with get_conn() as conn:
        job = _load_job(conn, job_id)
    if not job:
        return {"ok": False, "error": "no approved resume for this job"}
    if job["hitl_status"] not in ("approved", "edited"):
        return {"ok": False, "error": f"resume not approved (hitl={job['hitl_status']})"}
    pdf_missing = not job.get("final_pdf_path")
    if pdf_missing and interactive:
        # In manual/Overleaf mode there's no rendered PDF — the human attaches it in the
        # headed browser. Warn but proceed so the rest of the form still gets filled.
        pass

    track = job["base_track"]
    gaps: list[str] = []
    use_headless = headless if headless is not None else (not config.PLAYWRIGHT_HEADED or not interactive)
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Playwright not installed: {e}"}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=use_headless)
        page = browser.new_page()
        page.goto(job["jd_url"], wait_until="domcontentloaded", timeout=60000)

        # Follow portal -> employer ATS redirect if we started on a job portal.
        if any(d in page.url for d in _PORTAL_DOMAINS):
            _follow_apply_redirect(page)

        provider = _detect_provider(page.url)
        _fill_contact_fields(page)
        if not pdf_missing:
            _upload_resume(page, job["final_pdf_path"])
        gaps = _handle_screening(page, track)

        # Record gaps + flag the job; NEVER click submit.
        with get_conn() as conn:
            for q in gaps:
                screening.record_gap(conn, q)
            if gaps:
                conn.execute("UPDATE jobs SET status='flagged', flag_reason=? WHERE id=?",
                             (f"needs your input: {len(gaps)} screening Q(s)", job_id))
            log_run(conn, AGENT, f"job={job_id}", output_ref=f"provider={provider} gaps={len(gaps)}")

        if interactive:
            # Leave the browser open at the review screen for the human to submit.
            print("\n" + "=" * 70)
            print(f"  Form filled for job {job_id} ({provider}). Review the fields.")
            if pdf_missing:
                print("  No rendered PDF (manual/Overleaf mode) — attach your compiled resume by hand.")
            if gaps:
                print(f"  {len(gaps)} screening question(s) were LEFT BLANK and flagged in the")
                print("  dashboard (Screening Q&A gaps). Answer them, or fill them by hand now.")
            print("  >>> YOU click Submit. This agent never submits. <<<")
            print("  Close the browser window when done, then 'Mark applied' in the dashboard.")
            print("=" * 70 + "\n")
            try:
                page.wait_for_event("close", timeout=0)  # wait until human closes the tab
            except Exception:  # noqa: BLE001
                pass
        try:
            browser.close()
        except Exception:  # noqa: BLE001
            pass

    note = ("Non-interactive fill complete (headless) — no submit." if not interactive
            else "Browser closed. Mark applied in the dashboard once you submitted.")
    return {"ok": True, "job_id": job_id, "provider": provider, "gaps": gaps,
            "pdf_attached": not pdf_missing, "note": note}


def _follow_apply_redirect(page) -> None:
    for sel in ("a:has-text('Apply')", "button:has-text('Apply')", "a:has-text('Apply on company')"):
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                page.wait_for_load_state("domcontentloaded", timeout=30000)
                time.sleep(1.5)
                return
        except Exception:  # noqa: BLE001
            continue


def _fill_by_label(page, label_substr: str, value: str) -> bool:
    if not value:
        return False
    try:
        loc = page.get_by_label(re.compile(label_substr, re.I))
        if loc.count() > 0:
            loc.first.fill(value)
            return True
    except Exception:  # noqa: BLE001
        pass
    # Fallback: placeholder / name attribute
    try:
        el = page.query_selector(f"input[placeholder*='{label_substr}' i], "
                                 f"input[name*='{label_substr}' i], "
                                 f"input[aria-label*='{label_substr}' i]")
        if el:
            el.fill(value)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _fill_contact_fields(page) -> None:
    for label, value in _contact_values().items():
        _fill_by_label(page, label, value or "")


def _upload_resume(page, pdf_path: str) -> None:
    try:
        inputs = page.query_selector_all("input[type='file']")
        for inp in inputs:
            try:
                inp.set_input_files(pdf_path)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass


_Q_HINTS = ("experience", "years", "ctc", "notice", "authorization", "why", "salary",
            "relocate", "visa", "sponsor", "compensation", "availability", "expected",
            "current", "willing", "how many", "do you", "are you", "have you")


def _looks_like_question(text: str) -> bool:
    low = text.lower()
    return "?" in text or any(w in low for w in _Q_HINTS)


def _control_for_label(page, label_el):
    """Identify the form control a question label drives.
    Returns (kind, data): 'text'->el, 'textarea'->el, 'select'->(el, options),
    'radio'->[(el, option_text), ...], 'checkbox'->el, or (None, None)."""
    try:
        el = None
        for_id = label_el.get_attribute("for")
        if for_id:
            el = page.query_selector(f'[id="{for_id}"]')
        if el is None:                                  # control nested in the label
            el = label_el.query_selector("input, select, textarea")
        if el is None:
            return None, None
        tag = el.evaluate("e => e.tagName.toLowerCase()")
        if tag == "textarea":
            return "textarea", el
        if tag == "select":
            opts = [o.inner_text().strip() for o in el.query_selector_all("option")
                    if o.inner_text().strip()]
            return "select", (el, opts)
        typ = (el.get_attribute("type") or "text").lower()
        if typ == "checkbox":
            return "checkbox", el
        if typ == "radio":
            name = el.get_attribute("name")
            radios = page.query_selector_all(f'input[type="radio"][name="{name}"]') if name else [el]
            group = [(r, _radio_label(page, r)) for r in radios]
            return "radio", [(r, t) for r, t in group if t]
        return "text", el
    except Exception:  # noqa: BLE001
        return None, None


def _radio_label(page, radio_el) -> str:
    try:
        rid = radio_el.get_attribute("id")
        if rid:
            lbl = page.query_selector(f'label[for="{rid}"]')
            if lbl:
                return (lbl.inner_text() or "").strip()
        return (radio_el.get_attribute("value") or radio_el.get_attribute("aria-label") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _fill_control(kind, data, answer: str) -> bool:
    """Fill the resolved answer into the control, choosing the right option for
    dropdowns/radios. Returns True if it filled something."""
    try:
        if kind in ("text", "textarea"):
            data.fill(answer)
            return True
        if kind == "select":
            el, opts = data
            opt = screening.pick_option(answer, opts)
            if opt:
                el.select_option(label=opt)
                return True
        elif kind == "radio":
            opt = screening.pick_option(answer, [t for _, t in data])
            if opt:
                for r, t in data:
                    if t == opt:
                        r.check()
                        return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _handle_screening(page, track: str) -> list[str]:
    """Fill custom questions from the answer bank across text/dropdown/radio controls
    (semantic-matched when wording differs); unmatched questions become gaps. Checkboxes
    (often consent/legal) are left for the human. Never guesses an answer."""
    gaps: list[str] = []
    try:
        labels = page.query_selector_all("label")
    except Exception:  # noqa: BLE001
        return gaps

    with get_conn() as conn:
        for lab in labels:
            try:
                text = (lab.inner_text() or "").strip()
            except Exception:  # noqa: BLE001
                continue
            if not text or len(text) < 8:
                continue
            if any(k in text.lower() for k in _CONTACT_MAP):   # handled as contact already
                continue
            kind, data = _control_for_label(page, lab)
            if kind == "checkbox":                                # leave consent to the human
                continue
            structured = kind in ("select", "radio")
            if not (structured or _looks_like_question(text)):    # skip decorative labels (no LLM spam)
                continue
            answer = screening.resolve_answer(conn, text, track)
            if answer and kind and _fill_control(kind, data, answer):
                continue
            gaps.append(text)                                     # unanswered / unfillable -> flag
    return list(dict.fromkeys(gaps))


# ---------------- Human-confirmed submission logging ----------------

def mark_applied(job_id: int, ats_confirmation_ref: str = "") -> dict:
    """Called from the dashboard AFTER the human clicked submit. Logs applications row."""
    with get_conn() as conn:
        r = conn.execute(
            "SELECT id FROM resumes WHERE job_id=? ORDER BY id DESC LIMIT 1", (job_id,)).fetchone()
        resume_id = r["id"] if r else None
        cur = conn.execute(
            """INSERT INTO applications (job_id, resume_id, applied_at, ats_confirmation_ref, status)
               VALUES (?,?,?,?, 'applied')""",
            (job_id, resume_id, now_iso(), ats_confirmation_ref),
        )
        conn.execute("UPDATE jobs SET status='applied', flag_reason=NULL WHERE id=?", (job_id,))
        log_run(conn, AGENT, f"job={job_id}", output_ref=f"application={cur.lastrowid}")
        return {"ok": True, "application_id": cur.lastrowid, "job_id": job_id}
