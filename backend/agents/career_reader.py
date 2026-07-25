"""Career-Page Reader Agent.

For a company whose careers page has NO public ATS API (ats_type='unverified'), this opens
the EMPLOYER'S OWN public careers page in a headed/headless browser, extracts the rendered
text + links, and uses the LLM to pull out job listings. This is legitimate: it reads one
company's own public page at a time (driven by the user), not a portal aggregator, and
never scrapes LinkedIn/Indeed.

Requires the Playwright browser: `python -m playwright install chromium`.
"""
from __future__ import annotations

from urllib.parse import urljoin, urlparse

from backend import config
from backend.db.database import get_conn, log_run, now_iso
from backend.llm import client

AGENT = "career_reader"

_SYSTEM = (
    "You extract job listings from a company's careers-page content (rendered text + links). "
    "Return ONLY a JSON array of objects {title, location, url, jd_snippet}. "
    "Match each role's apply/detail link from the provided links by its anchor text; if none, "
    "leave url empty. jd_snippet = a short description if visible, else empty. "
    f"Only real engineering/software job postings relevant to: {config.OWNER_PROFILE}; "
    "skip nav links, blog posts, and non-engineering roles. If none, return []."
)

JOBS_SCHEMA = {
    "type": "object",
    "properties": {"jobs": {"type": "array", "items": {
        "type": "object",
        "properties": {"title": {"type": "string"}, "location": {"type": "string"},
                       "url": {"type": "string"}, "jd_snippet": {"type": "string"}},
        "required": ["title"]}}},
    "required": ["jobs"],
}


def _coerce(x):
    if isinstance(x, dict):
        if isinstance(x.get("jobs"), list):
            return x["jobs"]
        for v in x.values():
            if isinstance(v, list):
                return v
        return [x] if x.get("title") else []
    if not isinstance(x, list):
        raise ValueError("expected job array")
    return x


def read_career_page(url: str, headless: bool = True) -> list[dict]:
    """Render the page and LLM-extract job listings. Returns [{title, location, url, jd_snippet}]."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception:  # noqa: BLE001 — networkidle can time out on chatty pages; use what loaded
            pass
        try:
            body_text = page.inner_text("body")[:16000]
        except Exception:  # noqa: BLE001
            body_text = ""
        links = []
        try:
            raw = page.eval_on_selector_all(
                "a", "els => els.map(e => ({t: (e.innerText||'').trim(), h: e.href}))")
            seen = set()
            for lk in raw:
                h = lk.get("h", "")
                if h and lk.get("t") and h not in seen:
                    seen.add(h)
                    links.append(f"{lk['t'][:60]} -> {h}")
        except Exception:  # noqa: BLE001
            pass
        browser.close()

    if not body_text.strip():
        return []
    prompt = (f"Careers page: {url}\n\nPAGE TEXT:\n{body_text}\n\n"
              f"LINKS (anchor -> href):\n" + "\n".join(links[:120]))
    jobs = client.complete_json(prompt, system=_SYSTEM, tier="fast", max_tokens=3000,
                                coerce=_coerce, json_schema=JOBS_SCHEMA)
    # Resolve relative URLs against the page.
    for j in jobs:
        if j.get("url") and not urlparse(j["url"]).netloc:
            j["url"] = urljoin(url, j["url"])
    return jobs


def scout_company(company_id: int, headless: bool = True) -> dict:
    """Read a company's careers page and insert matching jobs (source='ats_api', since it's
    first-party employer data). Uses companies.careers_url."""
    with get_conn() as conn:
        row = conn.execute("SELECT id, name, careers_url FROM companies WHERE id=?",
                           (company_id,)).fetchone()
    if not row:
        return {"ok": False, "error": "company not found"}
    if not row["careers_url"]:
        return {"ok": False, "error": "no careers_url on this company — add one first"}

    try:
        jobs = read_career_page(row["careers_url"], headless=headless)
    except Exception as e:  # noqa: BLE001
        with get_conn() as conn:
            log_run(conn, AGENT, f"company={company_id}", validation_passed=False, error_text=str(e))
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "hint": "Run `python -m playwright install chromium` if the browser is missing."}

    inserted = 0
    with get_conn() as conn:
        for j in jobs:
            if not j.get("title"):
                continue
            ext = f"career:{company_id}:{abs(hash(j.get('url') or j['title'])) % 10**8}"
            cur = conn.execute(
                """INSERT OR IGNORE INTO jobs
                   (company_id, external_id, title, jd_text, jd_url, location, discovered_at, source, status)
                   VALUES (?,?,?,?,?,?,?, 'ats_api', 'new')""",
                (company_id, ext, j["title"], j.get("jd_snippet", ""),
                 j.get("url") or row["careers_url"], j.get("location", ""), now_iso()),
            )
            inserted += cur.rowcount if cur.rowcount > 0 else 0
        log_run(conn, AGENT, f"company={company_id}", output_ref=f"found={len(jobs)} inserted={inserted}")

    return {"ok": True, "company": row["name"], "found": len(jobs), "inserted": inserted}
