#!/usr/bin/env python
"""Job Application Agent — pipeline entrypoint.

Default (batch) run, suitable for cron or manual invocation:

    python run_pipeline.py                 # full batch: discover -> analyze -> tailor(queue)
                                           #  + post-apply: contacts -> outreach
    python run_pipeline.py --init          # create DB schema + seed companies (run once)
    python run_pipeline.py --discover      # discovery only (ATS + email alerts)
    python run_pipeline.py --analyze       # JD analysis only
    python run_pipeline.py --tailor        # queue resume diffs only
    python run_pipeline.py --postapply     # contact discovery + outreach for applied jobs
    python run_pipeline.py --report        # print the daily summary
    python run_pipeline.py --graph JOB_ID  # run the per-job LangGraph up to the HITL interrupt

The two human checkpoints (resume-diff approval, final apply click) happen in the
dashboard — this script never bypasses them and never submits an application.
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.db.database import init_db
from backend.db.seed import seed_companies


def _print(title: str, result) -> None:
    print(f"\n[{title}]")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


def cmd_init(verify: bool) -> None:
    init_db()
    n = seed_companies(verify=verify)
    _print("init", {"schema": "created", "companies_seeded": n,
                    "note": "Set verify=False (--no-verify) to skip network ATS detection."})


def cmd_discover() -> None:
    from backend.agents import email_parser, job_discovery
    _print("job_discovery", job_discovery.run())
    _print("email_parser", email_parser.run())


def cmd_analyze() -> None:
    from backend.agents import jd_analyzer
    _print("jd_analyzer", jd_analyzer.run())


def cmd_tailor() -> None:
    from backend.agents import resume_tailor
    _print("resume_tailor", resume_tailor.run())


def cmd_postapply() -> None:
    from backend.agents import contact_discovery, outreach_composer
    _print("contact_discovery", contact_discovery.run())
    _print("outreach_composer", outreach_composer.run())


def cmd_report() -> None:
    from backend.agents import daily_reporter
    _print("daily_reporter", daily_reporter.summary())


def cmd_tracker() -> None:
    from backend.agents import application_tracker
    _print("application_tracker", application_tracker.run())


def cmd_scout(area: str) -> None:
    from backend.agents import area_scout
    _print("area_scout", area_scout.scout_and_add(area))


def cmd_full() -> None:
    cmd_discover()
    cmd_analyze()
    cmd_tailor()
    cmd_postapply()
    cmd_tracker()      # refresh application statuses from Gmail
    cmd_report()
    print("\n>>> Resume diffs are queued for your approval in the dashboard.")
    print(">>> After approving, work the Apply Queue (you click submit each time).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Job Application Agent pipeline")
    ap.add_argument("--init", action="store_true")
    ap.add_argument("--no-verify", action="store_true", help="skip network ATS detection at seed")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--analyze", action="store_true")
    ap.add_argument("--tailor", action="store_true")
    ap.add_argument("--postapply", action="store_true")
    ap.add_argument("--tracker", action="store_true", help="reconstruct application status from Gmail")
    ap.add_argument("--scout", type=str, metavar="AREA", help="find + add companies hiring in an area")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--graph", type=int, metavar="JOB_ID")
    args = ap.parse_args()

    if args.init:
        cmd_init(verify=not args.no_verify)
        return 0
    if args.graph:
        from backend.graph.pipeline import run_job_graph
        _print("graph", run_job_graph(args.graph))
        return 0
    if args.scout:
        cmd_scout(args.scout)
        return 0

    ran = False
    for flag, fn in (("discover", cmd_discover), ("analyze", cmd_analyze),
                     ("tailor", cmd_tailor), ("postapply", cmd_postapply),
                     ("tracker", cmd_tracker), ("report", cmd_report)):
        if getattr(args, flag):
            fn(); ran = True
    if not ran:
        cmd_full()
    return 0


if __name__ == "__main__":
    sys.exit(main())
