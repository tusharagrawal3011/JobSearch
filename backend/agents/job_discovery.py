"""Job Discovery Agent.

Polls each company via its stored api_url (running ATS detection first if the company
is unverified/missing). Diffs against known external_ids, inserts new postings that
pass keyword + location filters. Output is validated downstream (JD Analyzer) — a job
missing jd_text / jd_url / company_id is flagged, not silently processed.
"""
from __future__ import annotations

import re

from backend import config
from backend.ats import detector
from backend.db.database import get_conn, log_run, now_iso

AGENT = "job_discovery"

# Word-boundary patterns so short keywords like "go"/"sde" don't match inside unrelated
# words ("category", "goals"). Discovery is intentionally broad but role-relevant: an
# engineering signal must appear, and a title must look like an engineering role.
_KW_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in config.KEYWORD_FILTERS) + r")\b", re.I)
_ROLE_RE = re.compile(
    r"\b(engineer|developer|sde|backend|full[\s-]?stack|software|architect|platform|infrastructure)\b",
    re.I,
)


def _matches_filters(title: str, jd_text: str, location: str) -> bool:
    loc = (location or "").lower()
    # Title must read like an engineering role (filters out sales/design/ops).
    if not _ROLE_RE.search(title or ""):
        return False
    # And a target keyword must appear as a whole word in the title or JD.
    if not (_KW_RE.search(title or "") or _KW_RE.search(jd_text or "")):
        return False
    loc_ok = (not loc) or any(l in loc for l in config.LOCATION_FILTERS) or "remote" in (jd_text or "").lower()
    return loc_ok


def _ensure_api(conn, company: dict) -> dict:
    """Resolve api_url via the detector if the company is unverified/missing one."""
    if company["ats_type"] in (None, "", "unverified") or not company["api_url"]:
        res = detector.detect_ats(company["name"], explicit_slug=company["ats_slug"])
        if res.ats_type != "unverified":
            conn.execute(
                "UPDATE companies SET ats_type=?, ats_slug=?, api_url=? WHERE id=?",
                (res.ats_type, res.ats_slug, res.api_url, company["id"]),
            )
            company = dict(company)
            company.update(ats_type=res.ats_type, ats_slug=res.ats_slug, api_url=res.api_url)
    return company


def run() -> dict:
    inserted, polled, skipped_unverified, errors = 0, 0, 0, 0
    with get_conn() as conn:
        companies = [dict(r) for r in conn.execute("SELECT * FROM companies").fetchall()]
        known: dict[int, set[str]] = {}
        for r in conn.execute("SELECT company_id, external_id FROM jobs WHERE external_id IS NOT NULL"):
            known.setdefault(r["company_id"], set()).add(r["external_id"])

        for company in companies:
            company = _ensure_api(conn, company)
            if company["ats_type"] == "unverified" or not company["api_url"]:
                skipped_unverified += 1
                continue
            try:
                postings = detector.fetch_postings(company["ats_type"], company["api_url"])
                polled += 1
            except Exception as e:  # noqa: BLE001
                errors += 1
                log_run(conn, AGENT, f"company={company['name']}", validation_passed=False, error_text=str(e))
                continue

            seen = known.get(company["id"], set())
            for p in postings:
                if p["external_id"] in seen:
                    continue
                if not _matches_filters(p["title"], p["jd_text"], p["location"]):
                    continue
                cur = conn.execute(
                    """INSERT OR IGNORE INTO jobs
                       (company_id, external_id, title, jd_text, jd_url, location,
                        discovered_at, source, status)
                       VALUES (?,?,?,?,?,?,?, 'ats_api', 'new')""",
                    (company["id"], p["external_id"], p["title"], p["jd_text"],
                     p["jd_url"], p["location"], now_iso()),
                )
                inserted += cur.rowcount if cur.rowcount > 0 else 0

        log_run(conn, AGENT, f"companies={len(companies)}",
                output_ref=f"polled={polled} inserted={inserted} unverified={skipped_unverified}")

    return {"agent": AGENT, "ok": True, "polled": polled, "inserted": inserted,
            "unverified_skipped": skipped_unverified, "errors": errors}
