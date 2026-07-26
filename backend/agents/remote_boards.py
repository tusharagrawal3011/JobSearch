"""Remote-board discovery.

Fetches from the OFFICIAL public JSON APIs of remote-job boards — first-party feeds these
sites publish for exactly this purpose, no scraping:
  * RemoteOK   https://remoteok.com/api
  * Remotive   https://remotive.com/api/remote-jobs
  * Arbeitnow  https://www.arbeitnow.com/api/job-board-api

Postings are filtered by the same keyword/location rules as ATS discovery and inserted into
`jobs` with a per-board source tag, then flow through the normal analyze -> tailor pipeline.
"""
from __future__ import annotations

import httpx

from backend import config
from backend.agents.job_discovery import _matches_filters
from backend.ats.detector import _strip_html
from backend.db.database import get_conn, log_run, now_iso, resolve_company_by_name, stable_id

AGENT = "remote_boards"
_TIMEOUT = httpx.Timeout(20.0)
_HEADERS = {"User-Agent": "job-agent/1.0 (+https://github.com/)"}

REMOTEOK = "https://remoteok.com/api"
REMOTIVE = "https://remotive.com/api/remote-jobs"
ARBEITNOW = "https://www.arbeitnow.com/api/job-board-api"


# --- Pure parsers (raw API JSON -> normalized postings); unit-testable offline. ---

def _parse_remoteok(data) -> list[dict]:
    out = []
    for j in data if isinstance(data, list) else []:
        if not j.get("position"):          # first element is a legal notice
            continue
        out.append({
            "external_id": str(j.get("id", "")), "title": j.get("position", ""),
            "company": j.get("company", ""), "jd_text": _strip_html(j.get("description", "")),
            "jd_url": j.get("url", ""), "location": j.get("location") or "Remote",
        })
    return out


def _parse_remotive(data) -> list[dict]:
    return [{
        "external_id": str(j.get("id", "")), "title": j.get("title", ""),
        "company": j.get("company_name", ""), "jd_text": _strip_html(j.get("description", "")),
        "jd_url": j.get("url", ""), "location": j.get("candidate_required_location") or "Remote",
    } for j in (data.get("jobs", []) if isinstance(data, dict) else [])]


def _parse_arbeitnow(data) -> list[dict]:
    return [{
        "external_id": str(j.get("slug", "")), "title": j.get("title", ""),
        "company": j.get("company_name", ""), "jd_text": _strip_html(j.get("description", "")),
        "jd_url": j.get("url", ""),
        "location": j.get("location") or ("Remote" if j.get("remote") else ""),
    } for j in (data.get("data", []) if isinstance(data, dict) else [])]


# board -> (api url, parser)
_BOARDS = {
    "remoteok": (REMOTEOK, _parse_remoteok),
    "remotive": (REMOTIVE, _parse_remotive),
    "arbeitnow": (ARBEITNOW, _parse_arbeitnow),
}


def _fetch(client: httpx.Client, board: str) -> list[dict]:
    url, parser = _BOARDS[board]
    r = client.get(url, headers=_HEADERS)
    r.raise_for_status()
    return parser(r.json())


# Remote boards list many region-locked "remote" roles (Americas/Europe only). Keep only
# postings a candidate in your target locations could actually take.
_ELIGIBLE_HINTS = ("india", "anywhere", "worldwide", "global", "asia", "apac")
_BARE_REMOTE = {"", "remote", "remote - anywhere", "fully remote", "worldwide"}


def _remote_eligible(location: str) -> bool:
    low = (location or "").strip().lower()
    if low in _BARE_REMOTE or any(x in low for x in _ELIGIBLE_HINTS):
        return True
    # A region-restricted listing is eligible only if it also names one of your locations.
    return any(l in low for l in config.LOCATION_FILTERS)


def _ingest(conn, board: str, postings: list[dict]) -> int:
    """Filter + insert one board's postings. Returns count inserted."""
    inserted = 0
    for p in postings:
        if not _matches_filters(p["title"], p["jd_text"], p["location"]):
            continue
        if not _remote_eligible(p["location"]):     # skip region-locked (e.g. Americas-only)
            continue
        ext = f"{board}:{p['external_id'] or stable_id(p['jd_url'] or p['title'])}"
        company_id = resolve_company_by_name(conn, p["company"] or "Unknown (remote board)")
        cur = conn.execute(
            """INSERT OR IGNORE INTO jobs
               (company_id, external_id, title, jd_text, jd_url, location,
                discovered_at, source, status)
               VALUES (?,?,?,?,?,?,?,?, 'new')""",
            (company_id, ext, p["title"], p["jd_text"], p["jd_url"],
             p["location"], now_iso(), board),
        )
        inserted += cur.rowcount if cur.rowcount > 0 else 0
    return inserted


def run(boards: list[str] | None = None) -> dict:
    boards = [b for b in (boards or config.REMOTE_BOARDS) if b in _BOARDS]
    inserted, fetched, errors = 0, 0, 0
    with get_conn() as conn, httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for board in boards:
            try:
                postings = _fetch(client, board)
                fetched += len(postings)
                inserted += _ingest(conn, board, postings)
            except Exception as e:  # noqa: BLE001
                errors += 1
                log_run(conn, AGENT, f"board={board}", validation_passed=False, error_text=str(e))
        log_run(conn, AGENT, f"boards={','.join(boards)}", output_ref=f"fetched={fetched} inserted={inserted}")

    return {"agent": AGENT, "ok": True, "boards": boards, "fetched": fetched,
            "inserted": inserted, "errors": errors}
