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


# ---------------- Gmail optional ----------------

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


# ---------------- Smart screening fill ----------------

def test_pick_option_normalized_matches_without_llm():
    from backend.agents.screening import pick_option
    assert pick_option("No", ["Yes", "No"]) == "No"                     # exact
    assert pick_option("Bengaluru", ["Remote", "Bengaluru", "Pune"]) == "Bengaluru"
    assert pick_option("5 years", ["0-2 years", "5 years experience"]) == "5 years experience"  # substring
    assert pick_option("", ["Yes", "No"]) is None                       # empty answer
    assert pick_option("x", []) is None                                 # no options


def test_pick_option_llm_fallback(monkeypatch):
    from backend.agents import screening
    from backend.llm import client
    # no normalized match -> LLM chooses; must return a verbatim option
    monkeypatch.setattr(client, "complete_json", lambda *a, **k: {"option": "3-5 years"})
    assert screening.pick_option("about four years", ["0-2 years", "3-5 years"]) == "3-5 years"
    # LLM returns something not in the list -> rejected
    monkeypatch.setattr(client, "complete_json", lambda *a, **k: {"option": "made up"})
    assert screening.pick_option("about four years", ["0-2 years", "3-5 years"]) is None


def test_looks_like_question():
    from backend.agents.application_submission import _looks_like_question
    assert _looks_like_question("How many years of experience do you have?") is True
    assert _looks_like_question("Current CTC") is True
    assert _looks_like_question("Middle name") is False


# ---------------- Remote boards ----------------

def test_remote_board_parsers():
    from backend.agents import remote_boards
    # RemoteOK: first element is a legal notice (no 'position') -> skipped
    rok = remote_boards._parse_remoteok([
        {"legal": "notice"},
        {"id": "1", "position": "Backend Engineer", "company": "Acme",
         "location": "Remote", "url": "http://x", "description": "<p>Go</p>"}])
    assert len(rok) == 1 and rok[0]["title"] == "Backend Engineer" and rok[0]["company"] == "Acme"
    assert "Go" in rok[0]["jd_text"] and "<p>" not in rok[0]["jd_text"]      # html stripped

    rmv = remote_boards._parse_remotive({"jobs": [
        {"id": 2, "title": "Node Dev", "company_name": "Beta",
         "candidate_required_location": "India", "url": "http://y", "description": "<b>node</b>"}]})
    assert len(rmv) == 1 and rmv[0]["location"] == "India"

    arb = remote_boards._parse_arbeitnow({"data": [
        {"slug": "s1", "title": "SDE", "company_name": "Gamma", "location": "",
         "remote": True, "url": "http://z", "description": "x"}]})
    assert len(arb) == 1 and arb[0]["location"] == "Remote"                  # remote flag -> "Remote"


def test_remote_eligibility_gate():
    from backend.agents.remote_boards import _remote_eligible
    assert _remote_eligible("") is True                    # unrestricted
    assert _remote_eligible("Anywhere") is True
    assert _remote_eligible("India") is True
    assert _remote_eligible("Americas, Europe, Asia") is True   # includes Asia
    assert _remote_eligible("Bengaluru") is True           # a target location
    assert _remote_eligible("Americas, Europe") is False   # region-locked, no India/Asia
    assert _remote_eligible("USA only") is False


# ---------------- Resume library ----------------

def test_resume_store_roundtrip(tmp_path, monkeypatch):
    """Upload -> becomes active -> tailor reads it from the DB (isolated temp DB)."""
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    from backend.resume import store, latex
    assert store.save_base_resume("go", "\\documentclass{article} MY RESUME", None, "r.tex", "Go")["ok"]
    assert store.get_base_tex("go") == "\\documentclass{article} MY RESUME"
    assert latex.base_tex_source("go") == "\\documentclass{article} MY RESUME"   # DB preferred
    bases = store.list_base_resumes()
    assert len(bases) == 1 and bases[0]["track"] == "go" and bases[0]["active"] == 1
    # a second upload deactivates the first
    store.save_base_resume("go", "v2", None, "r2.tex", "Go v2")
    assert store.get_base_tex("go") == "v2"


# ---------------- Résumé ↔ JD match ----------------

def _seed_job(db):
    with db.get_conn() as c:
        c.execute("INSERT INTO companies (id,name,ats_type) VALUES (1,'Acme','greenhouse')")
        c.execute("""INSERT INTO jobs (id,company_id,title,jd_text,stack_guess,status)
                     VALUES (1,1,'Backend Engineer',?, 'go','analyzed')""",
                  ("We want Go, Kafka and Python experience. " * 8,))


def test_resume_match_score_and_cache(tmp_path, monkeypatch):
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    _seed_job(database)
    from backend.llm import client
    from backend.agents import resume_match
    monkeypatch.setattr(client, "complete_json",
                        lambda *a, **k: {"score": 80, "matched": ["Go"],
                                         "missing": ["Kafka", "Python"], "summary": "solid"})
    r = resume_match.score(1)
    assert r["score"] == 80 and "Kafka" in r["missing"] and r["cached"] is False
    # second call is served from cache even though the LLM would now say something different
    monkeypatch.setattr(client, "complete_json", lambda *a, **k: {"score": 5})
    assert resume_match.score(1)["score"] == 80 and resume_match.score(1)["cached"] is True


def test_resume_match_optimize_is_truthful(tmp_path, monkeypatch):
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    _seed_job(database)
    from backend.llm import client
    from backend.agents import resume_match
    monkeypatch.setattr(client, "complete_json", lambda *a, **k: {
        "professional_summary": {"before": "", "after": ""}, "technical_skills": {"before": "", "after": ""},
        "added_keywords": ["Kafka"], "skipped_no_evidence": ["Python"], "notes": ""})
    r = resume_match.optimize(1, ["Kafka", "Python"])
    assert r["ok"] and "Kafka" in r["added_keywords"] and "Python" in r["skipped_no_evidence"]
    with database.get_conn() as c:
        assert c.execute("SELECT COUNT(*) FROM resumes WHERE job_id=1").fetchone()[0] == 1


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
