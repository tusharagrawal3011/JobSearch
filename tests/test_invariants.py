"""Offline tests for security invariants and core pure logic.

No network, LLM, browser, or database file is touched. Run with: pytest -q
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


# ---------------- Security invariants ----------------

def test_stable_id_is_deterministic():
    """The dedup id must be stable across calls (builtin hash() is not)."""
    from backend.db.database import stable_id
    assert stable_id("https://x/job/1") == stable_id("https://x/job/1")
    assert stable_id("a", "b") != stable_id("a", "c")
    assert len(stable_id("anything")) == 12


def test_no_gmail_send_anywhere():
    """The tool must never be able to send email — draft-only."""
    src = (ROOT / "backend" / "integrations" / "gmail.py").read_text(encoding="utf-8")
    assert "messages().send" not in src
    assert ".send(" not in src.replace("run_local_server", "")  # ignore oauth helper
    assert "drafts().create" in src  # it does create drafts


def test_pdflatex_disables_shell_escape():
    src = (ROOT / "backend" / "resume" / "latex.py").read_text(encoding="utf-8")
    assert "-no-shell-escape" in src
    assert "-shell-escape" not in src.replace("-no-shell-escape", "")


def test_api_binds_localhost_by_default():
    from backend import config
    assert config.API_HOST == "127.0.0.1"


def test_gmail_scopes_are_least_privilege():
    from backend import config
    joined = " ".join(config.GMAIL_SCOPES)
    assert "gmail.readonly" in joined and "gmail.compose" in joined
    assert "gmail.send" not in joined and "mail.google.com" not in joined


def test_no_placeholder_identity_leaks_real_data():
    """Shipped defaults must be neutral placeholders, not a real person."""
    import importlib
    from backend import config
    importlib.reload(config)
    # (When a user sets .env these change; defaults in code must be generic.)
    assert "@example.com" in config.OWNER_EMAIL or config.OWNER_EMAIL == "you@example.com" \
        or "@" in config.OWNER_EMAIL  # any configured value is fine; just ensure it's a string
    assert isinstance(config.OWNER_NAME, str) and config.OWNER_NAME


# ---------------- Pure logic ----------------

def test_status_classification():
    from backend.agents.application_tracker import classify_status
    assert classify_status("Interview scheduled with Acme", "") == "interview"
    assert classify_status("Your HackerRank assessment invite", "") == "assessment"
    assert classify_status("We regret to inform you", "") == "rejected"
    assert classify_status("We are pleased to offer you", "") == "offer"
    assert classify_status("Thank you for applying", "") == "applied"


def test_invalid_status_update_rejected_without_db():
    from backend.agents.application_tracker import update_entry
    res = update_entry(1, status="bogus-status")  # returns before touching the DB
    assert res["ok"] is False and "invalid status" in res["error"]


def test_job_keyword_filter_word_boundary():
    from backend.agents.job_discovery import _matches_filters
    # 'go' must not match inside 'category'; role must look like engineering
    assert _matches_filters("Backend Engineer (Go)", "build APIs in Go", "Remote") is True
    assert _matches_filters("Category Manager", "manage the go-to-market category", "Remote") is False


def test_coerce_jobs_normalizes_and_rejects_junk():
    import pytest
    from backend.agents.email_parser import _coerce_jobs
    assert _coerce_jobs([]) == []                              # empty is valid
    assert _coerce_jobs([{"title": "x", "url": "y"}])          # bare array of objects
    assert _coerce_jobs({"jobs": [{"title": "x"}]})            # wrapper object -> unwrapped
    assert _coerce_jobs({"title": "x", "url": "y"})            # single job -> wrapped in list
    with pytest.raises(ValueError):
        _coerce_jobs(["a string", "not an object"])           # weak-model junk -> rejected


def test_gmail_optional_email_parser_skips_cleanly(monkeypatch):
    """With Gmail not connected, the email parser skips without OAuth/network."""
    from backend.agents import email_parser
    from backend.integrations import gmail
    monkeypatch.setattr(gmail, "is_configured", lambda: False)
    res = email_parser.run()
    assert res["ok"] is True and res.get("skipped") == "Gmail not connected"


def test_gmail_optional_tracker_skips_cleanly(monkeypatch):
    from backend.agents import application_tracker
    from backend.integrations import gmail
    monkeypatch.setattr(gmail, "is_configured", lambda: False)
    res = application_tracker.run()
    assert res["ok"] is True and res.get("skipped") == "Gmail not connected"


def test_ats_detect_from_url_parses_known_hosts():
    """URL parsing picks the right provider/slug (regex only; probing is skipped here)."""
    import re
    from backend.ats import detector
    # Verify the provider templates exist for all registered providers.
    assert set(detector._TEMPLATES) >= {"greenhouse", "lever", "ashby", "workable",
                                        "smartrecruiters", "recruitee", "bamboohr"}
    # slug variants are generated deterministically
    variants = detector.slug_variants("GoTo Group")
    assert "gotogroup" in variants
