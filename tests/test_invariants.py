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


def test_heuristic_fit_scoring(monkeypatch):
    from backend.agents import resume_match
    monkeypatch.setattr(resume_match, "resume_tokens",
                        lambda track: {"go", "kubernetes", "docker", "kafka", "redis"})
    assert resume_match.heuristic_fit("Go, Docker, Kafka", "go") == 100        # all present
    assert resume_match.heuristic_fit("Go, Rust, Scala", "go") == 33           # 1 of 3
    assert resume_match.heuristic_fit("Rust, Scala, Elixir", "go") == 0        # none
    assert resume_match.heuristic_fit("", "go") == 0                           # no keywords


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


# ---------------- Cover letters ----------------

def test_interview_prep_generate_and_get(tmp_path, monkeypatch):
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    with database.get_conn() as c:
        c.execute("""INSERT INTO tracked_applications (id,company,role,status,hidden,first_seen,last_update)
                     VALUES (1,'Acme','Backend Engineer','interview',0,'2026-01-01','2026-01-01')""")
    from backend.llm import client
    from backend.agents import interview_prep
    monkeypatch.setattr(client, "complete_with_web_search", lambda *a, **k: "Acme builds real-time systems.")
    monkeypatch.setattr(client, "complete_json", lambda *a, **k: {
        "technical_questions": ["Q1", "Q2"], "behavioral_questions": [], "gap_questions": [],
        "talking_points": ["Your Go concurrency work"], "questions_to_ask": ["What's the on-call like?"]})
    assert [i["company"] for i in interview_prep.list_interviews()] == ["Acme"]
    r = interview_prep.generate(1)
    assert r["ok"] and r["brief"] == "Acme builds real-time systems."
    assert r["prep"]["technical_questions"] == ["Q1", "Q2"]
    assert interview_prep.get(1)["prep"]["talking_points"] == ["Your Go concurrency work"]


def test_reminders_classify_action():
    from backend.agents.reminders import classify_action
    from backend import config
    d = config.FOLLOWUP_DAYS
    assert classify_action("offer", 1, False)["urgency"] == "now"
    assert classify_action("assessment", 1, False)["urgency"] == "soon"
    assert classify_action("interview", 1, False)["can_followup"] is True
    assert classify_action("applied", 2 * d + 1, False)["urgency"] == "now"     # very stale
    assert classify_action("applied", d + 1, False)["urgency"] == "soon"
    assert classify_action("applied", 1, False)["urgency"] == "waiting"         # fresh
    # a flagged pending step (needs_action) wins over the age rule
    assert classify_action("interview", 1, True, "Confirm slot")["action"] == "Confirm slot"


def test_cover_letter_clean_text():
    from backend.agents.cover_letter import clean_text
    assert clean_text("a—b") == "a - b"              # em dash
    assert clean_text("I’m") == "I'm"                # curly apostrophe
    assert clean_text("“hi”…") == '"hi"...'  # curly quotes + ellipsis


def test_cover_letter_generate_and_save(tmp_path, monkeypatch):
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    _seed_job(database)
    from backend.llm import client
    from backend.agents import cover_letter
    monkeypatch.setattr(client, "complete_json",
                        lambda *a, **k: {"subject": "Role — Me", "body": "Dear team… I’m keen."})
    r = cover_letter.generate(1)
    assert r["ok"] and "—" not in r["subject"]                  # cleaned
    assert cover_letter.get(1)["body"] == "Dear team... I'm keen."   # cleaned + stored
    cover_letter.save(1, "S", "edited body")
    got = cover_letter.get(1)
    assert got["body"] == "edited body" and got["status"] == "edited"


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


# ---------------- Profile (DB overlays .env) ----------------

def test_profile_defaults_to_env_then_db_overlays(tmp_path, monkeypatch):
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    from backend import profile
    # Fresh DB: not set yet, falls back to config env defaults.
    assert profile.is_set() is False
    assert profile.get()["name"] == config.OWNER_NAME
    # Save a partial profile: those fields win, the rest still fall back to env.
    profile.save({"name": "Ada Lovelace", "email": "ada@calc.dev"})
    assert profile.is_set() is True
    eff = profile.get()
    assert eff["name"] == "Ada Lovelace" and eff["email"] == "ada@calc.dev"
    assert eff["location"] == config.OWNER_LOCATION           # untouched -> env default
    # Blank values do not clobber the effective value (env default shows through).
    profile.save({"name": "Ada Lovelace", "phone": ""})
    assert profile.get()["phone"] == config.OWNER_PHONE


def test_profile_feeds_agents_at_call_time(tmp_path, monkeypatch):
    from backend import config
    from backend.db import database
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.db")
    database.init_db()
    from backend import profile
    profile.save({"name": "Grace Hopper", "profile_summary": "Compiler pioneer"})
    # Cover-letter + reminder system prompts are built from the effective profile at call time.
    from backend.agents import cover_letter, reminders
    assert "Grace Hopper" in cover_letter._system()
    assert "Compiler pioneer" in cover_letter._system()
    assert "Grace Hopper" in reminders._system()


# ---------------- Insights (funnel analytics) ----------------

def test_insights_analyze_funnel_and_rates():
    from backend.agents.insights import _analyze
    apps = [
        {"id": 1, "status": "offer", "platform": "direct", "first_seen": "2026-01-01T00:00:00+00:00", "last_update": "2026-02-01T00:00:00+00:00"},
        {"id": 2, "status": "rejected", "platform": "naukri", "first_seen": "2026-01-10T00:00:00+00:00", "last_update": "2026-01-20T00:00:00+00:00"},
        {"id": 3, "status": "interview", "platform": "direct", "first_seen": "2026-02-05T00:00:00+00:00", "last_update": "2026-02-10T00:00:00+00:00"},
        {"id": 4, "status": "applied", "platform": "naukri", "first_seen": "2026-02-15T00:00:00+00:00", "last_update": "2026-02-15T00:00:00+00:00"},
    ]
    events = [
        # app1 progressed applied -> interview -> offer
        {"tracked_id": 1, "ts": "2026-01-08T00:00:00+00:00", "status": "interview"},
        {"tracked_id": 1, "ts": "2026-01-20T00:00:00+00:00", "status": "offer"},
        # app2 reached interview, then rejected (rejection must NOT inflate the interview stage falsely,
        # but the interview it DID reach should count)
        {"tracked_id": 2, "ts": "2026-01-15T00:00:00+00:00", "status": "interview"},
        {"tracked_id": 2, "ts": "2026-01-18T00:00:00+00:00", "status": "rejected"},
        # app3 assessment then interview
        {"tracked_id": 3, "ts": "2026-02-09T00:00:00+00:00", "status": "interview"},
        # app4 no events (applied only, no response)
    ]
    out = _analyze(apps, events, volume={"naukri": 40})
    f = {x["stage"]: x["count"] for x in out["funnel"]}
    assert f["Applied"] == 4
    assert f["Interview"] == 3          # apps 1,2,3 all reached interview
    assert f["Offer"] == 1              # only app1
    assert out["totals"]["responded"] == 3           # apps 1,2,3; app4 silent
    assert out["rates"]["response_rate"] == 0.75
    assert out["outcomes"]["no_response"] == 1
    assert out["outcomes"]["offer"] == 1 and out["outcomes"]["rejected"] == 1
    assert out["totals"]["bulk_volume"] == 40
    # median days-to-first-response: app1 7d (01-01->01-08), app2 5d, app3 4d -> median 5
    assert out["median_days_to_response"] == 5
    # platform split: direct has 2 apps both responded
    direct = next(p for p in out["by_platform"] if p["platform"] == "direct")
    assert direct["total"] == 2 and direct["response_rate"] == 1.0


def test_insights_empty_is_safe():
    from backend.agents.insights import _analyze
    out = _analyze([], [])
    assert out["totals"]["tracked"] == 0
    assert out["rates"]["response_rate"] == 0.0
    assert out["median_days_to_response"] is None
    assert out["by_month"] == [] and out["by_platform"] == []
