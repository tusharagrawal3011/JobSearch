"""Area Scout Agent.

Given a location (e.g. "HSR Layout, Bangalore"), uses Gemini's Google Search grounding
to find companies HEADQUARTERED in / actively hiring in that area for roles matching the
owner's profile (backend, Go/Node, agentic-AI). Each discovered company is run through the
ATS-detection utility and added to `companies` — so Job Discovery starts polling the ones
with public Greenhouse/Lever/Ashby boards automatically, and the rest are flagged
'unverified' for the Playwright/manual flow.

This is legitimate: it reads the public web via search grounding to find company NAMES,
then only touches those companies' own first-party public ATS APIs. No scraping.
"""
from __future__ import annotations

from backend import config
from backend.ats import detector
from backend.db.database import get_conn, log_run, now_iso
from backend.db.seed import add_company
from backend.llm import client

AGENT = "area_scout"

def _system() -> str:
    from backend import profile
    return (
        "You are a tech-recruiting researcher. Using web search, find real companies that are "
        "HEADQUARTERED IN or have an engineering office in the given area AND are currently hiring "
        f"engineers matching this profile: {profile.get()['profile_summary']}. Focus on product companies and startups. "
        "For careers_url, STRONGLY PREFER the company's ATS job-board URL if they use one — i.e. a "
        "boards.greenhouse.io/<slug>, jobs.lever.co/<slug>, or jobs.ashbyhq.com/<slug> link — since "
        "that lets the system poll their openings automatically. Fall back to their own careers page "
        "only if no ATS board is found. "
        "Return ONLY a JSON array (max 15) of objects: "
        "{company, hq_area, careers_url, roles (short string of open roles), evidence (where you saw they're hiring)}. "
        "Only include companies you can verify from a real public page. No duplicates, no staffing "
        "agencies, no job-aggregator sites. If none, return []."
    )


def _coerce(x):
    if isinstance(x, dict):
        for v in x.values():
            if isinstance(v, list):
                return v
        return [x] if x.get("company") else []
    return x if isinstance(x, list) else []


def scout(area: str, extra_keywords: str = "") -> list[dict]:
    """Return candidate companies (not yet added) for the area."""
    from backend import profile
    p = profile.get()
    locations = p["location_filters"] or ", ".join(config.LOCATION_FILTERS)
    prompt = (
        f"Area: {area}\n"
        f"Candidate profile: {p['profile_summary']}. "
        f"Target locations: {locations}. {extra_keywords}\n\n"
        "Find companies in this area actively hiring engineers now. Return the JSON array."
    )
    raw = client.complete_with_web_search(prompt, system=_system(), tier="fast", max_tokens=3000)
    candidates = _coerce(client._parse_json(raw)) if raw.strip() else []
    out = []
    for c in candidates:
        if isinstance(c, dict) and c.get("company"):
            out.append({
                "company": str(c["company"]).strip(),
                "hq_area": c.get("hq_area", area),
                "careers_url": c.get("careers_url", ""),
                "roles": c.get("roles", ""),
                "evidence": c.get("evidence", ""),
            })
    return out


def scout_and_add(area: str, extra_keywords: str = "") -> dict:
    """Scout the area, run ATS detection on each new company, and add them to `companies`.
    Returns a summary with the detected ATS type per company."""
    try:
        candidates = scout(area, extra_keywords)
    except Exception as e:  # noqa: BLE001
        with get_conn() as conn:
            log_run(conn, AGENT, f"area={area}", validation_passed=False, error_text=str(e))
        return {"agent": AGENT, "ok": False, "error": str(e)}

    with get_conn() as conn:
        existing = {r["name"].lower() for r in conn.execute("SELECT name FROM companies").fetchall()}

    added, skipped, results = 0, 0, []
    for c in candidates:
        if c["company"].lower() in existing:
            skipped += 1
            results.append({**c, "status": "already tracked"})
            continue
        row = add_company(c["company"], c.get("careers_url", ""), verify=True)  # runs ATS detection
        added += 1
        results.append({
            "company": c["company"], "roles": c.get("roles", ""),
            "ats_type": row["ats_type"], "ats_slug": row.get("ats_slug"),
            "pollable": row["ats_type"] in ("greenhouse", "lever", "ashby"),
            "status": "added",
        })

    with get_conn() as conn:
        log_run(conn, AGENT, f"area={area}", output_ref=f"found={len(candidates)} added={added}")

    pollable = sum(1 for r in results if r.get("pollable"))
    return {"agent": AGENT, "ok": True, "area": area, "found": len(candidates),
            "added": added, "already_tracked": skipped, "pollable_now": pollable,
            "companies": results}
