"""Application Tracker Agent.

Reconstructs the user's ENTIRE application history + current status from their own
Gmail — application confirmations, recruiter emails, interview invites, assessments,
rejections, offers. Deliberately RULE-BASED (no LLM): fast, deterministic, and free,
which matters because there are ~100 such emails and local-LLM classification would take
hours. The LLM chain is reserved for the job-extraction agents.

Precision matters more than recall here — a noisy tracker is worse than a lean one — so:
  * job-portal blasts and the user's own SENT replies are excluded at the query level,
  * status emails that don't reach a STRONG status (interview/assessment/offer/rejected)
    are dropped rather than defaulted to "applied",
  * marketing/education spam is filtered by keyword,
  * junk company extractions are skipped.

Produces: tracked_applications (one row per company) · tracked_events (timeline) ·
tracker_volume (batch "you applied for N jobs" counts).
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime

from backend import config
from backend.db.database import get_conn, log_run, now_iso
from backend.integrations import gmail

AGENT = "application_tracker"

# Direct application confirmations (precise). Naukri/Indeed batch counts handled as volume.
CONFIRMATION_Q = ('subject:("Indeed Application" OR "you applied" OR "application received" '
                  'OR "thank you for applying" OR "application submitted" '
                  'OR "we received your application" OR "we have received your application") '
                  'newer_than:180d -in:sent')

# Status updates — only from substantive senders (companies/agencies/ATS), NOT job portals
# (those send invites/marketing, not real status), and never the user's own sent mail.
STATUS_Q = ('subject:(interview OR "next steps" OR assessment OR "coding challenge" '
            'OR "online test" OR "technical assessment" OR hackerrank OR "regret to inform" '
            'OR "not moving forward" OR "not selected" OR "pleased to offer" OR "offer of employment") '
            'newer_than:180d -in:sent '
            '-from:jobalert.indeed.com -from:match.indeed.com -from:naukri.com '
            '-from:indeed.com -from:linkedin.com -from:timesjobs.com -from:instahyre.com '
            '-from:cutshort.io -from:hirist.com')

COMPANY_DOMAINS = {
    "capgemini.com": "Capgemini", "happiestminds.com": "Happiest Minds",
    "yipitdata.com": "YipitData", "vectorshift.ai": "VectorShift",
    "onemoregame.ink": "One More Game", "micro1.ai": "micro1",
    "accenture.com": "Accenture", "cyberforcehq.com": "CyberForce HQ",
    "deccanexperts.ai": "Deccan AI Experts", "csscompany.com": "Picnic",
    "rsystems.com": "R Systems", "turing.com": "Turing", "nagarro.com": "Nagarro",
}
AGENCY_DOMAINS = {"teamlease.com", "innovasolutions.com", "applytojob.com",
                  "hackerrankforwork.com", "mail-intervue.com", "myworkday.com",
                  "smartrecruiters.com", "greenhouse.io", "lever.co", "ashbyhq.com"}

# Education-marketing + promotional spam to ignore.
NOISE_RE = re.compile(
    r"\b(emba|pgdm|m\.?tech|\bmba\b|executive program|great lakes|degree|certification|"
    r"certificate|\bcourse\b|webinar|enroll|scholarship|cashback|getaway|% off|flat \d|"
    r"sale|coupon|tick tock|don.t miss|limited time|discount|bootcamp|"
    r"new job vacanc|job vacancies|job openings|hiring for multiple|walk-in drive)\b", re.I)

# Company extractions that are obviously junk → skip the email.
STOP_COMPANY = {"gmail", "jobtitle", "job title", "bengaluru", "getready", "yourinterview",
                "reminder", "interview", "re", "fwd", "next steps", "nextsteps"}

STATUS_RANK = {"applied": 1, "assessment": 2, "interview": 3, "rejected": 4, "withdrawn": 4, "offer": 5}
TERMINAL = {"offer", "rejected", "withdrawn"}
_STRONG = {"interview", "assessment", "offer", "rejected"}


def _domain(sender: str) -> str:
    m = re.search(r"@([\w.-]+)", sender or "")
    return m.group(1).lower() if m else ""


def _local(sender: str) -> str:
    m = re.search(r"([\w.+-]+)@", sender or "")
    return m.group(1).lower() if m else ""


def _root_company(domain: str) -> str:
    core = domain.split(".")[-2] if domain.count(".") >= 1 else domain
    return core.replace("-", " ").title()


def _is_own(sender: str) -> bool:
    from backend import profile
    return profile.get()["email"].lower() in (sender or "").lower()


def classify_status(subject: str, snippet: str) -> str:
    t = f"{subject} {snippet}".lower()
    if any(k in t for k in ("pleased to offer", "offer letter", "job offer",
                            "delighted to offer", "offer of employment", "extend an offer")):
        return "offer"
    if any(k in t for k in ("regret to inform", "not moving forward", "not selected",
                            "decided not to proceed", "position has been filled",
                            "unfortunately", "other candidates", "interview feedback")):
        return "rejected"
    if any(k in t for k in ("interview", "call letter", "walk-in", "walkin", "next round",
                            "next stage", "schedule your interview", "availability for",
                            "in-person interview", "f2f", "next steps")):
        return "interview"
    if any(k in t for k in ("assessment", "coding challenge", "hackerrank", "online test",
                            "take-home", "assignment", "complete your interview",
                            "screening", "login link")):
        return "assessment"
    return "applied"


# Optional gazetteer of company names matched anywhere in a subject/snippet FIRST — it
# reliably collapses multi-email threads (e.g. several interview emails from one company)
# into a single tracked row. Ships EMPTY; add the companies you apply to (or set
# TRACKER_KNOWN_COMPANIES in .env as a comma-separated list) to improve dedup. When empty,
# the heuristics below still extract company names, just with slightly lower precision.
import os as _os

KNOWN_COMPANIES = [c.strip() for c in _os.getenv("TRACKER_KNOWN_COMPANIES", "").split(",") if c.strip()]
_KNOWN_SORTED = sorted(KNOWN_COMPANIES, key=len, reverse=True)

# Words that mean an extracted string is NOT a company name.
_JUNK_WORDS = ("interview", "application", "apply", "applying", "received", "invite",
               "invitation", "letter", " day", "venue", "reminder", "get ready", "action",
               "next step", "schedule", "slot", "developer", "engineer", "vacan", "job",
               "position", "role", "confirmation", "thank", "update", "your ", "202", "login")


def _is_junk(name: str) -> bool:
    low = f" {name.lower()} "
    if config.OWNER_NAME and config.OWNER_NAME.lower() in name.lower():   # the user's own name
        return True
    return (not name or len(name) < 2 or NOISE_RE.search(name)
            or any(w in low for w in _JUNK_WORDS) or bool(re.search(r"\d{2}", name)))


def _clean_company(name: str) -> str:
    name = re.sub(r"\b(is|are|will|has|have|for you|position|role|team|careers?)\b.*$",
                  "", name, flags=re.I)
    return name.strip(" .!?-–|/:")


def extract_company(sender: str, subject: str, snippet: str) -> str:
    domain = _domain(sender)
    if domain in COMPANY_DOMAINS:
        return COMPANY_DOMAINS[domain]
    text = f"{subject} {snippet}"
    # 1. Gazetteer — first known company mentioned anywhere.
    low = text.lower()
    for name in _KNOWN_SORTED:
        if name.lower() in low:
            return name
    # 2. Workday sender local-part (accenture@myworkday.com -> Accenture).
    if domain == "myworkday.com":
        loc = _local(sender)
        if loc and loc not in ("no-reply", "noreply", "notification"):
            return loc.replace(".", " ").title()
    # 3. Heuristic patterns, validated against the junk guard.
    candidates = []
    for seg in re.split(r"\s*\|\s*", subject):          # each pipe segment is a candidate
        candidates.append(seg)
    for src in (subject, snippet):
        for pat in (r"\bwith ([A-Z][\w.&' -]{2,40})", r"\bat ([A-Z][\w.&' -]{2,40})",
                    r"\bto ([A-Z][\w.&' -]{2,40})", r"[-–] ([A-Z][\w.&' ]{2,40})$",
                    r"\[([^\]|]+)"):
            m = re.search(pat, src or "")
            if m:
                candidates.append(m.group(1))
    for cand in candidates:
        name = _clean_company(cand)
        if not _is_junk(name) and name[:1].isupper() and 1 <= len(name.split()) <= 4:
            return name
    return _root_company(domain)


def extract_role(subject: str) -> str:
    for pat in (r"Indeed Application:\s*(.+)", r"Application Received for\s*(.+?):",
                r"applying (?:to|for)(?: the post of)?\s*(.+?)(?: with | at |:|$)",
                r"interest in (?:the |being part.*?)?(?:position of )?(.+?)(?: with | at |\.|$)",
                r"role of\s*(.+?)(?: is | has |\.|$)"):
        m = re.search(pat, subject or "", re.I)
        if m:
            return m.group(1).strip(" .!-–|")[:80]
    return ""


def _norm_key(company: str) -> str:
    core = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    for suf in ("india", "pvtltd", "pvt", "ltd", "technologies", "tech", "services",
                "solutions", "inc", "llc", "consulting", "labs", "software", "group"):
        core = core.replace(suf, "")
    return core or (company or "unknown").lower()


def _action_hint(status: str, text: str) -> tuple[int, str]:
    t = text.lower()
    if status == "assessment" and any(k in t for k in ("pending", "reminder", "expire",
                                                       "complete", "friendly reminder", "login link")):
        return 1, "Pending assessment — complete it"
    if status == "interview" and any(k in t for k in ("confirm", "availability", "schedule",
                                                      "submit availability", "action required")):
        return 1, "Confirm / schedule the interview"
    return 0, ""


def _iso(date_hdr: str) -> str:
    try:
        return parsedate_to_datetime(date_hdr).isoformat()
    except Exception:  # noqa: BLE001
        return now_iso()


_VOLUME_RE = re.compile(r"you applied for (\d+) job", re.I)


def _handle_volume(conn, msg) -> bool:
    m = _VOLUME_RE.search(msg["subject"])
    if not m:
        return False
    platform = "naukri" if "naukri" in _domain(msg["sender"]) else "indeed"
    conn.execute(
        """INSERT OR IGNORE INTO tracker_volume (platform, applied_on, count, gmail_msg_id)
           VALUES (?,?,?,?)""",
        (platform, _iso(msg["date"])[:10], int(m.group(1)), msg["id"]),
    )
    return True


def _upsert(conn, company, role, status, msg, platform):
    key = _norm_key(company)
    text = f"{msg['subject']} {msg['snippet']}"
    needs, hint = _action_hint(status, text)
    ts = _iso(msg["date"])
    row = conn.execute("SELECT * FROM tracked_applications WHERE thread_key=?", (key,)).fetchone()
    if row is None:
        cur = conn.execute(
            """INSERT INTO tracked_applications
               (company, role, platform, status, first_seen, last_update, latest_subject,
                latest_snippet, source_domain, thread_key, needs_action, action_hint)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (company, role, platform, status, ts, ts, msg["subject"], msg["snippet"],
             _domain(msg["sender"]), key, needs, hint),
        )
        tid = cur.lastrowid
    else:
        tid = row["id"]
        new_rank, cur_rank = STATUS_RANK.get(status, 1), STATUS_RANK.get(row["status"], 1)
        best = (status if (new_rank >= cur_rank or status in TERMINAL)
                and row["status"] not in TERMINAL else row["status"])
        if row["manual_status"]:            # user set the status by hand — never override it
            best = row["status"]
        newer = ts >= (row["last_update"] or "")
        conn.execute(
            """UPDATE tracked_applications SET status=?, last_update=?,
               latest_subject=CASE WHEN ? THEN ? ELSE latest_subject END,
               latest_snippet=CASE WHEN ? THEN ? ELSE latest_snippet END,
               role=COALESCE(NULLIF(role,''), ?), needs_action=?, action_hint=?
               WHERE id=?""",
            (best, max(ts, row["last_update"] or ts), newer, msg["subject"], newer,
             msg["snippet"], role, needs, hint, tid),
        )
    conn.execute(
        """INSERT OR IGNORE INTO tracked_events
           (tracked_id, ts, status, subject, snippet, sender, gmail_msg_id)
           VALUES (?,?,?,?,?,?,?)""",
        (tid, ts, status, msg["subject"], msg["snippet"], msg["sender"], msg["id"]),
    )
    return True


def _track(conn, msg, require_strong: bool) -> str:
    """Track one email. Returns 'tracked' | 'dropped' | 'skipped'."""
    if _is_own(msg["sender"]) or NOISE_RE.search(f"{msg['subject']} {msg['snippet']}"):
        return "skipped"
    status = classify_status(msg["subject"], msg["snippet"])
    if require_strong and status not in _STRONG:      # weak status-query hit = noise
        return "dropped"
    company = extract_company(msg["sender"], msg["subject"], msg["snippet"])
    if _norm_key(company) in STOP_COMPANY or not re.search(r"[A-Za-z]", company):
        return "skipped"
    role = extract_role(msg["subject"])
    platform = "agency" if _domain(msg["sender"]) in AGENCY_DOMAINS else "direct"
    _upsert(conn, company, role, status, msg, platform)
    return "tracked"


def run(max_results: int = 300) -> dict:
    if not gmail.is_configured():
        return {"agent": AGENT, "ok": True, "skipped": "Gmail not connected"}
    try:
        confirms = gmail.search_messages(CONFIRMATION_Q, max_results)
        statuses = gmail.search_messages(STATUS_Q, max_results)
    except Exception as e:  # noqa: BLE001
        with get_conn() as conn:
            log_run(conn, AGENT, "gmail", validation_passed=False, error_text=str(e))
        return {"agent": AGENT, "ok": False, "error": str(e)}

    seen, tracked, volume, dropped, skipped = set(), 0, 0, 0, 0
    with get_conn() as conn:
        for msg, require_strong in [(m, False) for m in confirms] + [(m, True) for m in statuses]:
            if msg["id"] in seen:
                continue
            seen.add(msg["id"])
            if not require_strong and _handle_volume(conn, msg):
                volume += 1
                continue
            outcome = _track(conn, msg, require_strong)
            tracked += outcome == "tracked"
            dropped += outcome == "dropped"
            skipped += outcome == "skipped"
        log_run(conn, AGENT, f"emails={len(seen)}",
                output_ref=f"tracked={tracked} volume={volume} dropped={dropped} skipped={skipped}")

    return {"agent": AGENT, "ok": True, "emails_scanned": len(seen), "tracked_events": tracked,
            "volume_emails": volume, "dropped_weak": dropped, "noise_skipped": skipped}


def summary() -> dict:
    with get_conn() as conn:
        apps = [dict(r) for r in conn.execute(
            """SELECT * FROM tracked_applications WHERE hidden=0
               ORDER BY CASE status WHEN 'offer' THEN 0 WHEN 'interview' THEN 1
                        WHEN 'assessment' THEN 2 WHEN 'applied' THEN 3 ELSE 4 END,
               last_update DESC""").fetchall()]
        status_counts = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, COUNT(*) n FROM tracked_applications WHERE hidden=0 GROUP BY status")}
        vol = {r["platform"]: r["total"] for r in conn.execute(
            "SELECT platform, SUM(count) total FROM tracker_volume GROUP BY platform")}
        return {
            "applications": apps,
            "status_counts": status_counts,
            "volume_by_platform": vol,
            "total_volume_applications": sum(vol.values()),
            "active_processes": sum(status_counts.get(s, 0) for s in ("assessment", "interview")),
            "needs_action": [dict(r) for r in conn.execute(
                "SELECT id, company, role, status, action_hint FROM tracked_applications WHERE needs_action=1 AND hidden=0")],
        }


def update_entry(tracked_id: int, status: str | None = None, hidden: bool | None = None) -> dict:
    """Manual override from the dashboard. Setting a status pins it (manual_status=1) so a
    later Gmail refresh won't overwrite the user's call."""
    sets, params = [], []
    if status is not None:
        if status not in STATUS_RANK:
            return {"ok": False, "error": f"invalid status '{status}'"}
        sets += ["status=?", "manual_status=1"]
        params.append(status)
    if hidden is not None:
        sets.append("hidden=?")
        params.append(1 if hidden else 0)
    if not sets:
        return {"ok": False, "error": "nothing to update"}
    params.append(tracked_id)
    with get_conn() as conn:
        # `sets` contains only hardcoded fragments ("status=?", "hidden=?", ...); every value
        # is bound via `params`, so this f-string is not SQL-injectable.
        conn.execute(f"UPDATE tracked_applications SET {', '.join(sets)} WHERE id=?", params)
    return {"ok": True, "id": tracked_id, "status": status, "hidden": hidden}


def detail(tracked_id: int) -> dict:
    with get_conn() as conn:
        app = conn.execute("SELECT * FROM tracked_applications WHERE id=?", (tracked_id,)).fetchone()
        events = conn.execute(
            "SELECT * FROM tracked_events WHERE tracked_id=? ORDER BY ts DESC", (tracked_id,)).fetchall()
        return {"application": dict(app) if app else None, "events": [dict(e) for e in events]}
