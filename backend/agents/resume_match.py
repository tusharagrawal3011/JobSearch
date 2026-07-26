"""Résumé ↔ JD matching (Simplify-style).

For a job it computes a match score + the keywords the résumé is matching vs. missing, and
can produce a keyword-optimized résumé. Guardrail: the optimizer only weaves in keywords the
candidate has real evidence for in their résumé — it never fabricates skills. Keywords with no
basis are returned separately as "add only if true", so the résumé stays honest.
"""
from __future__ import annotations

import json
import re

from backend.db.database import get_conn, log_run, now_iso
from backend.llm import client
from backend.resume import latex

AGENT = "resume_match"
TRACK_MAP = {"go": "go", "node": "node", "ambiguous": "go", "other": "go"}

_SYSTEM_SCORE = (
    "You are an ATS résumé screener. Given a job description and a candidate's résumé, score "
    "how well the résumé matches the JD on keyword/skill coverage (an ATS-style match). "
    "Return JSON: {score: <0-100 integer>, matched: [keywords/skills the JD wants that ARE "
    "present in the résumé], missing: [important keywords/skills/tools the JD wants that are "
    "ABSENT or only weakly present], summary: <1-2 sentence explanation>}. "
    "Focus on hard skills, tools, technologies and concrete requirements — not soft skills. "
    "Keep each keyword short (1-3 words). Do not invent."
)

_SYSTEM_OPT = (
    "You optimize a résumé to better match a JD by weaving in SPECIFIED keywords — but ONLY "
    "where the candidate plausibly has that skill given evidence already in their résumé. "
    "NEVER fabricate experience, tools, or skills the résumé gives no basis for. "
    "Return JSON: {professional_summary:{before,after}, technical_skills:{before,after}, "
    "added_keywords:[keywords you incorporated truthfully], "
    "skipped_no_evidence:[requested keywords you did NOT add because the résumé shows no basis], "
    "notes:string}. Only touch the one-line summary and the skills list; keep everything grounded "
    "in the résumé's real content."
)


def _track(job: dict) -> str:
    return TRACK_MAP.get(job.get("stack_guess") or "ambiguous", "go")


# ---------------- Cheap heuristic fit (instant, no LLM) — for ranking everything ----------------

_TOKEN = re.compile(r"[a-z0-9+#.]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall((text or "").lower()) if len(t) > 1}


_RESUME_TOKENS: dict[str, set[str]] = {}


def resume_tokens(track: str) -> set[str]:
    """Token set of the base résumé for a track (cached per process)."""
    if track not in _RESUME_TOKENS:
        _RESUME_TOKENS[track] = _tokens(latex.base_resume_text(track))
    return _RESUME_TOKENS[track]


def heuristic_fit(job_keywords_csv: str, track: str) -> int:
    """Rough 0-100 fit from overlap of the JD's extracted keywords with the résumé's tokens.
    Instant and free — used to rank jobs before (or without) an LLM score."""
    kws = [k.strip().lower() for k in (job_keywords_csv or "").split(",") if k.strip()]
    if not kws:
        return 0
    rtok = resume_tokens(track)
    hits = sum(1 for k in kws if any(part in rtok for part in _TOKEN.findall(k)))
    return round(100 * hits / len(kws))


def clear_cache() -> None:
    _RESUME_TOKENS.clear()


def rank(limit: int = 100) -> list[dict]:
    """Analyzed jobs ranked by best available fit score: the cached LLM score if present,
    otherwise the instant heuristic. Best matches first."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT j.id AS job_id, j.title, j.stack_guess, j.keywords, j.seniority, j.status,
                      co.name AS company, m.score AS llm_score
               FROM jobs j JOIN companies co ON co.id=j.company_id
               LEFT JOIN jd_match m ON m.job_id=j.id
               WHERE j.status IN ('analyzed','tailoring','ready_to_apply')
                     AND length(j.jd_text) > 100""").fetchall()
    out = []
    for r in rows:
        r = dict(r)
        track = _track(r)
        if r["llm_score"] is not None:
            r["score"], r["score_type"] = int(r["llm_score"]), "ai"
        else:
            r["score"], r["score_type"] = heuristic_fit(r["keywords"], track), "heuristic"
        r.pop("llm_score", None)
        out.append(r)
    out.sort(key=lambda x: (x["score_type"] != "ai", -x["score"]))  # AI-scored first, then by score
    return out[:limit]


def score_batch(limit: int = 20) -> dict:
    """LLM-score the top unscored analyzed jobs (by heuristic), caching each result.
    Keeps cost bounded — scores the most promising `limit` jobs per call."""
    ranked = [j for j in rank(500) if j["score_type"] == "heuristic"]
    ranked.sort(key=lambda x: -x["score"])
    scored = 0
    for j in ranked[:limit]:
        res = score(j["job_id"])
        if res.get("score") is not None and not res.get("error"):
            scored += 1
    return {"agent": AGENT, "ok": True, "scored": scored, "remaining_unscored": max(0, len(ranked) - scored)}


def score(job_id: int, force: bool = False) -> dict:
    with get_conn() as conn:
        if not force:
            cached = conn.execute("SELECT * FROM jd_match WHERE job_id=?", (job_id,)).fetchone()
            if cached:
                d = dict(cached)
                d["matched"] = json.loads(d.get("matched") or "[]")
                d["missing"] = json.loads(d.get("missing") or "[]")
                d["cached"] = True
                return d
        job = conn.execute(
            """SELECT j.*, co.name AS company FROM jobs j JOIN companies co ON co.id=j.company_id
               WHERE j.id=?""", (job_id,)).fetchone()
    if not job:
        return {"ok": False, "error": "job not found"}
    job = dict(job)
    if not (job.get("jd_text") or "").strip():
        return {"ok": False, "error": "this job has no JD text to score against"}

    track = _track(job)
    resume = latex.base_resume_text(track)
    result = client.complete_json(
        f"JOB: {job['title']} @ {job['company']}\n\nJOB DESCRIPTION:\n{job['jd_text'][:12000]}\n\n"
        f"CANDIDATE RÉSUMÉ ({track} track):\n{resume[:12000]}",
        system=_SYSTEM_SCORE, tier="fast", max_tokens=1500,
    )
    out = {
        "job_id": job_id, "track": track,
        "score": int(result.get("score", 0)),
        "matched": result.get("matched", []),
        "missing": result.get("missing", []),
        "summary": result.get("summary", ""),
        "computed_at": now_iso(),
    }
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO jd_match (job_id, track, score, matched, missing, summary, computed_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET track=excluded.track, score=excluded.score,
                 matched=excluded.matched, missing=excluded.missing, summary=excluded.summary,
                 computed_at=excluded.computed_at""",
            (job_id, track, out["score"], json.dumps(out["matched"]),
             json.dumps(out["missing"]), out["summary"], out["computed_at"]),
        )
        log_run(conn, AGENT, f"job={job_id}", output_ref=f"score={out['score']}")
    out["cached"] = False
    return out


def optimize(job_id: int, keywords: list[str] | None = None) -> dict:
    """Produce a keyword-optimized résumé for the job (truthful weave), stored as a tailored
    résumé (pending approval) so it shows in the Diff Approval queue + base-vs-tailored view."""
    from backend.agents import resume_tailor

    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        return {"ok": False, "error": "job not found"}
    job = dict(job)
    track = _track(job)
    # Default to the missing keywords from the cached score if none passed.
    if not keywords:
        s = score(job_id)
        keywords = s.get("missing", [])
    if not keywords:
        return {"ok": False, "error": "no keywords to optimize for"}

    base_text = latex.base_resume_text(track)
    diff = client.complete_json(
        f"TARGET KEYWORDS TO INCORPORATE (only if truthful): {', '.join(keywords)}\n\n"
        f"JD: {job['title']}\n{(job.get('jd_text') or '')[:8000]}\n\n"
        f"RÉSUMÉ ({track} track):\n{base_text[:12000]}",
        system=_SYSTEM_OPT, tier="smart", max_tokens=2500,
    )

    base_tex = latex.base_tex_source(track)
    tailored_tex = resume_tailor._apply_diff_to_tex(base_tex, diff) if base_tex else None
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO resumes (job_id, base_track, diff_json, tex_content, hitl_status)
               VALUES (?,?,?,?, 'pending')""",
            (job_id, track, json.dumps(diff, ensure_ascii=False), tailored_tex),
        )
        conn.execute("UPDATE jobs SET status='tailoring' WHERE id=? AND status='analyzed'", (job_id,))
        log_run(conn, AGENT, f"job={job_id}", output_ref=f"optimized resume={cur.lastrowid}")
        rid = cur.lastrowid
    return {
        "ok": True, "resume_id": rid, "track": track,
        "added_keywords": diff.get("added_keywords", []),
        "skipped_no_evidence": diff.get("skipped_no_evidence", []),
        "notes": diff.get("notes", ""),
        "has_tex": bool(tailored_tex),
    }
