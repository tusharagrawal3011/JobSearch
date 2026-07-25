"""ATS detection + posting-fetch utilities.

This is a STANDING UTILITY, not a one-off seed script. `detect_ats(name)` is called:
  * at seed time for the 4 unverified companies,
  * automatically whenever a company is added via the dashboard, and
  * by the Job Discovery agent when a company's ats_type is 'unverified'/missing.

It only ever touches first-party public JSON APIs the companies publish themselves
(Greenhouse / Lever / Ashby). No scraping of LinkedIn/Indeed anywhere.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

GREENHOUSE = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
WORKABLE = "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true"
SMARTRECRUITERS = "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
RECRUITEE = "https://{slug}.recruitee.com/api/offers/"
BAMBOOHR = "https://{slug}.bamboohr.com/careers/list"

# Ordered list of (provider, url_template) tried during name-based detection.
PROVIDERS = (
    ("greenhouse", GREENHOUSE), ("lever", LEVER), ("ashby", ASHBY),
    ("workable", WORKABLE), ("smartrecruiters", SMARTRECRUITERS),
    ("recruitee", RECRUITEE), ("bamboohr", BAMBOOHR),
)
_TEMPLATES = dict(PROVIDERS)

_TIMEOUT = httpx.Timeout(15.0)


@dataclass
class ATSResult:
    ats_type: str  # greenhouse | lever | ashby | unverified
    ats_slug: Optional[str] = None
    api_url: Optional[str] = None
    job_count: int = 0
    tried: list[str] = field(default_factory=list)


def slug_variants(company_name: str) -> list[str]:
    """Generate plausible ATS slugs from a company name."""
    base = company_name.strip().lower()
    cleaned = re.sub(r"[^a-z0-9 ]", "", base)
    words = cleaned.split()
    variants = {
        "".join(words),                       # gotogroup
        "-".join(words),                      # goto-group
        words[0] if words else cleaned,       # goto
        re.sub(r"\b(inc|labs|ai|technologies|tech|group|india)\b", "", cleaned).replace(" ", ""),
    }
    return [v for v in dict.fromkeys(v for v in variants if v)]  # dedupe, keep order


def _probe(client: httpx.Client, url: str) -> Optional[int]:
    """Return a job count if the endpoint responds with a valid board, else None."""
    try:
        r = client.get(url, headers={"User-Agent": "job-agent/1.0"})
        if r.status_code != 200:
            return None
        data = r.json()
    except Exception:
        return None

    # Greenhouse/Ashby/Workable: {"jobs":[...]}; Lever: [...]; SmartRecruiters: {"content":[...]};
    # Recruitee: {"offers":[...]}; BambooHR: {"result":[...]}.
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        for key in ("jobs", "content", "offers", "result", "postings", "data"):
            if isinstance(data.get(key), list):
                return len(data[key])
    return None


def detect_from_url(careers_url: str) -> Optional[ATSResult]:
    """Extract the ATS + slug directly from a careers/jobs URL when it points at a known
    ATS host (far more reliable than guessing a slug from the company name)."""
    if not careers_url:
        return None
    u = careers_url.strip().lower()
    patterns = [
        ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_-]+)"),
        ("greenhouse", r"([a-z0-9_-]+)\.greenhouse\.io"),
        ("lever", r"jobs\.lever\.co/([a-z0-9_-]+)"),
        ("ashby", r"(?:jobs\.)?ashbyhq\.com/([a-z0-9_-]+)"),
        ("workable", r"apply\.workable\.com/([a-z0-9_-]+)"),
        ("workable", r"([a-z0-9_-]+)\.workable\.com"),
        ("smartrecruiters", r"(?:careers|jobs)\.smartrecruiters\.com/([a-z0-9_-]+)"),
        ("smartrecruiters", r"smartrecruiters\.com/([a-z0-9_-]+)"),
        ("recruitee", r"([a-z0-9_-]+)\.recruitee\.com"),
        ("bamboohr", r"([a-z0-9_-]+)\.bamboohr\.com"),
    ]
    for provider, pat in patterns:
        m = re.search(pat, u)
        if m:
            slug = m.group(1)
            api_url = _TEMPLATES[provider].format(slug=slug)
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                count = _probe(client, api_url)
            if count:
                return ATSResult(provider, slug, api_url, count, [f"url:{provider}:{slug}"])
    return None


def detect_ats(company_name: str, explicit_slug: Optional[str] = None,
               careers_url: Optional[str] = None) -> ATSResult:
    """Try Greenhouse -> Lever -> Ashby against slug variants. First hit wins.

    Falls back to ATSResult('unverified') meaning: no public ATS API found — likely
    Workday or a custom career page, needs the semi-auto Playwright flow / manual handling.
    """
    # A real careers URL pointing at a known ATS host is the most reliable signal.
    from_url = detect_from_url(careers_url) if careers_url else None
    if from_url:
        return from_url

    slugs = [explicit_slug] if explicit_slug else []
    slugs += [s for s in slug_variants(company_name) if s not in slugs]

    tried: list[str] = []
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for provider, template in PROVIDERS:
            for slug in slugs:
                url = template.format(slug=slug)
                tried.append(f"{provider}:{slug}")
                count = _probe(client, url)
                if count:  # a real board with at least one posting
                    return ATSResult(provider, slug, url, count, tried)

    return ATSResult("unverified", tried=tried)


def fetch_postings(ats_type: str, api_url: str) -> list[dict]:
    """Fetch raw postings for a known ATS. Returns a normalized list of dicts with
    keys: external_id, title, jd_text, jd_url, location."""
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        r = client.get(api_url, headers={"User-Agent": "job-agent/1.0"})
        r.raise_for_status()
        data = r.json()

    if ats_type == "greenhouse":
        return [_norm_greenhouse(j) for j in data.get("jobs", [])]
    if ats_type == "lever":
        return [_norm_lever(j) for j in data]
    if ats_type == "ashby":
        return [_norm_ashby(j) for j in data.get("jobs", [])]
    if ats_type == "workable":
        return [_norm_workable(j) for j in data.get("jobs", [])]
    if ats_type == "recruitee":
        return [_norm_recruitee(j) for j in data.get("offers", [])]
    if ats_type == "smartrecruiters":
        return _fetch_smartrecruiters(api_url, data.get("content", []))
    if ats_type == "bamboohr":
        return _fetch_bamboohr(api_url, data.get("result", []))
    return []


def _fetch_smartrecruiters(list_url: str, postings: list) -> list[dict]:
    """SmartRecruiters listing lacks the JD; fetch each posting's detail for jd_text."""
    base = list_url.split("?")[0]
    out = []
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for p in postings:
            jd = ""
            try:
                d = client.get(f"{base}/{p.get('id')}", headers={"User-Agent": "job-agent/1.0"}).json()
                secs = ((d.get("jobAd") or {}).get("sections") or {})
                jd = " ".join(_strip_html((secs.get(k) or {}).get("text", ""))
                              for k in ("jobDescription", "qualifications", "additionalInformation"))
            except Exception:  # noqa: BLE001
                pass
            loc = p.get("location") or {}
            out.append({
                "external_id": str(p.get("id", "")), "title": p.get("name", ""), "jd_text": jd,
                "jd_url": f"https://jobs.smartrecruiters.com/{p.get('company',{}).get('identifier','')}/{p.get('id','')}",
                "location": ", ".join(x for x in (loc.get("city"), loc.get("country")) if x),
            })
    return out


def _fetch_bamboohr(list_url: str, postings: list) -> list[dict]:
    """BambooHR careers/list lacks the JD; fetch each job's detail for jd_text."""
    base = list_url.rsplit("/list", 1)[0]
    out = []
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for p in postings:
            jid = p.get("id")
            jd = ""
            try:
                d = client.get(f"{base}/{jid}/detail", headers={"User-Agent": "job-agent/1.0"}).json()
                jd = _strip_html((d.get("result") or {}).get("jobOpeningShareUrl", "")) or \
                    _strip_html((d.get("result") or {}).get("description", ""))
            except Exception:  # noqa: BLE001
                pass
            loc = p.get("location") or {}
            out.append({
                "external_id": str(jid), "title": (p.get("jobOpeningName") or p.get("title", "")),
                "jd_text": jd, "jd_url": f"{base}/{jid}",
                "location": ", ".join(x for x in (loc.get("city"), loc.get("state"), loc.get("country")) if x),
            })
    return out


def _norm_workable(j: dict) -> dict:
    return {
        "external_id": str(j.get("shortcode") or j.get("id", "")),
        "title": j.get("title", ""),
        "jd_text": _strip_html(j.get("description", "")),
        "jd_url": j.get("url") or j.get("application_url", ""),
        "location": ", ".join(x for x in ((j.get("location") or {}).get("city"),
                                          (j.get("location") or {}).get("country")) if x),
    }


def _norm_recruitee(j: dict) -> dict:
    return {
        "external_id": str(j.get("id", "")),
        "title": j.get("title", ""),
        "jd_text": _strip_html(j.get("description", "")),
        "jd_url": j.get("careers_url") or j.get("url", ""),
        "location": j.get("location") or j.get("city", ""),
    }


def _strip_html(html: str) -> str:
    from bs4 import BeautifulSoup

    return BeautifulSoup(html or "", "lxml").get_text("\n", strip=True)


def _norm_greenhouse(j: dict) -> dict:
    return {
        "external_id": str(j.get("id", "")),
        "title": j.get("title", ""),
        "jd_text": _strip_html(j.get("content", "")),
        "jd_url": j.get("absolute_url", ""),
        "location": (j.get("location") or {}).get("name", ""),
    }


def _norm_lever(j: dict) -> dict:
    return {
        "external_id": str(j.get("id", "")),
        "title": j.get("text", ""),
        "jd_text": _strip_html(j.get("descriptionPlain") or j.get("description", "")),
        "jd_url": j.get("hostedUrl", ""),
        "location": (j.get("categories") or {}).get("location", ""),
    }


def _norm_ashby(j: dict) -> dict:
    return {
        "external_id": str(j.get("id", "")),
        "title": j.get("title", ""),
        "jd_text": _strip_html(j.get("descriptionHtml") or j.get("descriptionPlain", "")),
        "jd_url": j.get("jobUrl") or j.get("applyUrl", ""),
        "location": j.get("location", ""),
    }
