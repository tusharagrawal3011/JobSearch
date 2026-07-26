-- Job Application Agent System — SQLite schema.
-- Single local user, no concurrent writers. LangGraph's own SQLite checkpointer
-- lives in a separate file (langgraph_checkpoints.sqlite).

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  ats_type   TEXT,   -- greenhouse|lever|ashby|workable|smartrecruiters|recruitee|bamboohr|workday|unverified (open set)
  ats_slug   TEXT,
  api_url    TEXT,
  careers_url TEXT,
  stack_fit  TEXT,
  location   TEXT,
  priority   TEXT,
  notes      TEXT,
  added_at   TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
  id           INTEGER PRIMARY KEY,
  company_id   INTEGER REFERENCES companies(id),
  external_id  TEXT,
  title        TEXT,
  jd_text      TEXT,
  jd_url       TEXT,
  location     TEXT,
  stack_guess  TEXT CHECK(stack_guess IN ('go','node','ambiguous','other')),
  keywords     TEXT,
  seniority    TEXT,
  discovered_at TEXT,
  source       TEXT DEFAULT 'ats_api',   -- ats_api | *_alert | remoteok | remotive | arbeitnow | career_page ... (open set)
  status       TEXT CHECK(status IN ('new','analyzed','tailoring','ready_to_apply','applied','flagged','skipped')) DEFAULT 'new',
  flag_reason  TEXT,
  UNIQUE(company_id, external_id)
);

-- The user's uploaded base resumes (the resume library). One 'active' per track is used
-- for tailoring; older uploads are kept for history.
CREATE TABLE IF NOT EXISTS base_resumes (
  id           INTEGER PRIMARY KEY,
  track        TEXT,          -- go | node (or any label you use for a resume variant)
  label        TEXT,
  tex_content  TEXT,          -- LaTeX source (enables real tailoring + side-by-side view)
  pdf_path     TEXT,          -- stored PDF for upload to applications
  filename     TEXT,
  active       INTEGER DEFAULT 1,
  uploaded_at  TEXT
);

CREATE TABLE IF NOT EXISTS resumes (
  id             INTEGER PRIMARY KEY,
  job_id         INTEGER REFERENCES jobs(id),
  base_track     TEXT CHECK(base_track IN ('go','node')),
  diff_json      TEXT,
  tex_content    TEXT,        -- the tailored LaTeX (so the UI can show base vs tailored)
  final_pdf_path TEXT,
  hitl_status    TEXT CHECK(hitl_status IN ('pending','approved','edited','rejected')) DEFAULT 'pending',
  reviewed_at    TEXT
);

-- The user's profile (identity + search prefs), editable in the UI. Overlays the .env
-- defaults so a new user can set everything up without touching files. Single row (id=1).
CREATE TABLE IF NOT EXISTS profile (
  id               INTEGER PRIMARY KEY CHECK (id = 1),
  name             TEXT,
  first_name       TEXT,
  last_name        TEXT,
  email            TEXT,
  phone            TEXT,
  linkedin         TEXT,
  github           TEXT,
  location         TEXT,
  profile_summary  TEXT,
  keyword_filters  TEXT,
  location_filters TEXT,
  updated_at       TEXT
);

-- Interview prep per tracked application: company brief + likely questions + talking points.
CREATE TABLE IF NOT EXISTS interview_prep (
  id          INTEGER PRIMARY KEY,
  tracked_id  INTEGER UNIQUE REFERENCES tracked_applications(id),
  company     TEXT,
  role        TEXT,
  brief       TEXT,       -- company research brief (public web)
  prep_json   TEXT,       -- {technical_questions, behavioral_questions, gap_questions, talking_points, questions_to_ask}
  created_at  TEXT
);

-- Tailored cover letters per job (generated from the JD + résumé; honest, editable).
CREATE TABLE IF NOT EXISTS cover_letters (
  id          INTEGER PRIMARY KEY,
  job_id      INTEGER UNIQUE REFERENCES jobs(id),
  subject     TEXT,
  body        TEXT,
  status      TEXT DEFAULT 'draft',   -- draft | edited
  created_at  TEXT
);

-- Cached résumé↔JD match results (Simplify-style score + keyword gaps), per job.
CREATE TABLE IF NOT EXISTS jd_match (
  id           INTEGER PRIMARY KEY,
  job_id       INTEGER UNIQUE REFERENCES jobs(id),
  track        TEXT,
  score        INTEGER,
  matched      TEXT,   -- JSON array of keywords present in the résumé
  missing      TEXT,   -- JSON array of important JD keywords absent/weak in the résumé
  summary      TEXT,
  computed_at  TEXT
);

CREATE TABLE IF NOT EXISTS applications (
  id                   INTEGER PRIMARY KEY,
  job_id               INTEGER REFERENCES jobs(id),
  resume_id            INTEGER REFERENCES resumes(id),
  applied_at           TEXT,
  ats_confirmation_ref TEXT,
  status               TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
  id                 INTEGER PRIMARY KEY,
  company_id         INTEGER REFERENCES companies(id),
  name               TEXT,
  role_guess         TEXT,
  public_profile_url TEXT,
  source             TEXT,
  verified_by_human  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS outreach_drafts (
  id             INTEGER PRIMARY KEY,
  contact_id     INTEGER REFERENCES contacts(id),
  application_id INTEGER REFERENCES applications(id),
  channel        TEXT CHECK(channel IN ('email','linkedin')),
  draft_text     TEXT,
  subject_line   TEXT,
  gmail_draft_id TEXT,
  status         TEXT CHECK(status IN ('drafted','edited','sent_manually')) DEFAULT 'drafted',
  created_at     TEXT
);

-- Ships EMPTY. Rows are created on-demand when the Application agent hits an
-- unmatched screening question; answers are filled by the human via the dashboard.
CREATE TABLE IF NOT EXISTS screening_answers (
  id            INTEGER PRIMARY KEY,
  question_key  TEXT UNIQUE,
  question_text TEXT,
  answer_go     TEXT,
  answer_node   TEXT,
  last_updated  TEXT
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id                INTEGER PRIMARY KEY,
  agent_name        TEXT,
  input_ref         TEXT,
  output_ref        TEXT,
  validation_passed INTEGER,
  error_text        TEXT,
  ts                TEXT
);

-- ---- Application tracker (reconstructed from the user's own Gmail) ----
-- Distinct from `applications` (jobs the agent helped submit): these are ALL applications
-- the user made anywhere, with status inferred from confirmation/interview/rejection emails.
CREATE TABLE IF NOT EXISTS tracked_applications (
  id             INTEGER PRIMARY KEY,
  company        TEXT,
  role           TEXT,
  platform       TEXT,   -- direct | naukri | indeed | agency | ats
  status         TEXT CHECK(status IN ('applied','assessment','interview','offer','rejected','withdrawn')) DEFAULT 'applied',
  first_seen     TEXT,
  last_update    TEXT,
  latest_subject TEXT,
  latest_snippet TEXT,
  source_domain  TEXT,
  thread_key     TEXT UNIQUE,   -- normalized company+role for dedupe/upsert
  needs_action   INTEGER DEFAULT 0,
  action_hint    TEXT,
  hidden         INTEGER DEFAULT 0,   -- user hid this entry
  manual_status  INTEGER DEFAULT 0    -- user set status by hand; Gmail refresh won't override it
);

CREATE TABLE IF NOT EXISTS tracked_events (
  id              INTEGER PRIMARY KEY,
  tracked_id      INTEGER REFERENCES tracked_applications(id),
  ts              TEXT,
  status          TEXT,
  subject         TEXT,
  snippet         TEXT,
  sender          TEXT,
  gmail_msg_id    TEXT UNIQUE,   -- real Gmail id, or a synthetic 'manual-…' id for hand-logged updates
  manual          INTEGER DEFAULT 0   -- 1 = logged by the user (phone call, LinkedIn, etc.), not from Gmail
);

-- Batch "you applied for N jobs" emails (Naukri/Indeed) — volume, not individually trackable.
CREATE TABLE IF NOT EXISTS tracker_volume (
  id           INTEGER PRIMARY KEY,
  platform     TEXT,
  applied_on   TEXT,
  count        INTEGER,
  gmail_msg_id TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_tracked_status ON tracked_applications(status);
CREATE INDEX IF NOT EXISTS idx_tracked_events_tid ON tracked_events(tracked_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_id);
CREATE INDEX IF NOT EXISTS idx_resumes_hitl ON resumes(hitl_status);
