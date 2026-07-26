"""Insights — turn the reconstructed application history into search analytics.

Pure aggregation over `tracked_applications` + `tracked_events` (both built by the
Application Tracker from Gmail). No LLM, no network — it just answers "is my search
working?": funnel conversion, response/interview/offer rates, days-to-first-response,
month-over-month volume, and which platform actually converts.

The number-crunching lives in `_analyze(apps, events)` so it can be unit-tested with
plain dicts; `compute()` only loads the rows and hands them off.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median

from backend.db.database import get_conn

# Positive progression ladder. Rejected/withdrawn are NOT on it — a rejection can land at
# any stage, so how far an application actually got is read from the stages it *reached*
# (its events), not from the terminal 'rejected' status.
PROGRESS = {"applied": 1, "assessment": 2, "interview": 3, "offer": 4}
REJECTED = {"rejected", "withdrawn"}
STAGES = [("Applied", 1), ("Assessment", 2), ("Interview", 3), ("Offer", 4)]


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def _analyze(apps: list[dict], events: list[dict], volume: dict | None = None) -> dict:
    """apps: tracked_applications rows. events: tracked_events rows (tracked_id, ts, status).
    volume: {platform: total} of bulk 'you applied for N jobs' counts (context only)."""
    volume = volume or {}
    ev_by_app: dict[int, list[dict]] = defaultdict(list)
    for e in events:
        ev_by_app[e["tracked_id"]].append(e)

    total = len(apps)
    reached = {stage: 0 for _, stage in STAGES}   # apps that got at least this far
    responded = rejected_ct = offers = 0
    days_to_response: list[float] = []
    by_month: dict[str, dict] = defaultdict(lambda: {"applied": 0, "interview": 0, "offer": 0})
    by_platform: dict[str, dict] = defaultdict(lambda: {"total": 0, "responded": 0, "interview": 0, "offer": 0})

    for a in apps:
        evs = ev_by_app.get(a["id"], [])
        statuses = [a.get("status")] + [e.get("status") for e in evs]
        prog = max((PROGRESS.get(s, 0) for s in statuses), default=1) or 1
        is_rejected = any(s in REJECTED for s in statuses)
        did_respond = prog >= 2 or is_rejected

        for _, stage in STAGES:
            if prog >= stage:
                reached[stage] += 1
        if did_respond:
            responded += 1
        if is_rejected:
            rejected_ct += 1
        if prog >= PROGRESS["offer"]:
            offers += 1

        # Month buckets keyed on when the application first appeared.
        started = _parse(a.get("first_seen")) or _parse(a.get("last_update"))
        if started:
            m = started.strftime("%Y-%m")
            by_month[m]["applied"] += 1
            if prog >= PROGRESS["interview"]:
                by_month[m]["interview"] += 1
            if prog >= PROGRESS["offer"]:
                by_month[m]["offer"] += 1

        # Days from application to the first substantive (non-applied) event.
        if started and evs:
            responses = sorted(
                (_parse(e.get("ts")) for e in evs
                 if e.get("status") and e["status"] != "applied" and _parse(e.get("ts"))),
                key=lambda d: d,
            )
            if responses:
                delta = (responses[0] - started).days
                if delta >= 0:
                    days_to_response.append(delta)

        plat = (a.get("platform") or "unknown").lower()
        p = by_platform[plat]
        p["total"] += 1
        if did_respond:
            p["responded"] += 1
        if prog >= PROGRESS["interview"]:
            p["interview"] += 1
        if prog >= PROGRESS["offer"]:
            p["offer"] += 1

    funnel = [{"stage": name, "count": reached[stage]} for name, stage in STAGES]
    platforms = sorted(
        [{"platform": k, **v, "response_rate": _rate(v["responded"], v["total"])}
         for k, v in by_platform.items()],
        key=lambda x: (-x["total"], x["platform"]),
    )
    months = [{"month": m, **by_month[m]} for m in sorted(by_month)]

    return {
        "totals": {
            "tracked": total,
            "responded": responded,
            "active": reached[2] - offers - rejected_ct if total else 0,  # in-flight, non-terminal
            "bulk_volume": sum(volume.values()),
        },
        "funnel": funnel,
        "rates": {
            "response_rate": _rate(responded, total),
            "interview_rate": _rate(reached[3], total),
            "offer_rate": _rate(offers, total),
        },
        "outcomes": {
            "offer": offers,
            "rejected": rejected_ct,
            "no_response": total - responded,
            "in_progress": total - offers - rejected_ct - (total - responded),
        },
        "median_days_to_response": round(median(days_to_response), 1) if days_to_response else None,
        "by_month": months,
        "by_platform": platforms,
        "volume_by_platform": dict(volume),
    }


def compute() -> dict:
    with get_conn() as conn:
        apps = [dict(r) for r in conn.execute(
            "SELECT id, status, platform, first_seen, last_update FROM tracked_applications WHERE hidden=0")]
        events = [dict(r) for r in conn.execute(
            "SELECT tracked_id, ts, status FROM tracked_events")]
        volume = {r["platform"]: r["total"] for r in conn.execute(
            "SELECT platform, SUM(count) total FROM tracker_volume GROUP BY platform")}
    return _analyze(apps, events, volume)
