"""Central configuration loaded from environment (.env).

Every module imports settings from here so there is a single source of truth for
model strings, file paths, scopes, and the two-human-checkpoint invariants.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = parent of the backend/ package.
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path(name: str, default: str) -> Path:
    raw = os.getenv(name, default)
    p = Path(raw)
    return p if p.is_absolute() else (ROOT / p)


# ---- LLM provider chain ----
# Ordered fallback chain. The client tries each provider in turn: up to LLM_MAX_RETRIES
# attempts with exponential backoff per provider, then falls through to the next.
# Agents call by TIER ('fast' | 'smart'); each provider maps the tier to its own model.
# Add a new provider by registering a builder in backend/llm/providers.py and naming it here.
_chain = os.getenv("LLM_CHAIN", "").strip()
LLM_CHAIN = [p.strip().lower() for p in _chain.split(",") if p.strip()] or \
    [os.getenv("LLM_PROVIDER", "gemini").lower()]

LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "3"))
LLM_BACKOFF_BASE = float(os.getenv("LLM_BACKOFF_BASE", "1.0"))   # seconds, first backoff
LLM_BACKOFF_MAX = float(os.getenv("LLM_BACKOFF_MAX", "30"))       # seconds, backoff ceiling
LLM_VERBOSE = os.getenv("LLM_VERBOSE", "1") == "1"                # log retries/fallbacks

# Ollama (local, free — primary by default).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL_FAST = os.getenv("OLLAMA_MODEL_FAST", "llama3")
OLLAMA_MODEL_SMART = os.getenv("OLLAMA_MODEL_SMART", "llama3")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))         # context window for local models

# Gemini (Google AI Studio API key).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_FAST = os.getenv("GEMINI_MODEL_FAST", "gemini-2.5-flash")
GEMINI_MODEL_SMART = os.getenv("GEMINI_MODEL_SMART", "gemini-2.5-pro")
# Disable "thinking" on the fast tier (cheaper + faster for high-volume JSON tasks).
GEMINI_DISABLE_THINKING_FAST = os.getenv("GEMINI_DISABLE_THINKING_FAST", "1") == "1"

# Anthropic (optional).
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL_FAST = os.getenv("CLAUDE_MODEL_FAST", "claude-sonnet-5")
ANTHROPIC_MODEL_SMART = os.getenv("CLAUDE_MODEL_SMART", "claude-opus-4-8")

# OpenAI / OpenAI-compatible (optional). Set OPENAI_BASE_URL for compatible endpoints
# (Together, Groq, OpenRouter, local vLLM, etc.).
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
OPENAI_MODEL_FAST = os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini")
OPENAI_MODEL_SMART = os.getenv("OPENAI_MODEL_SMART", "gpt-4o")

# Back-compat aliases (still referenced by the raw grounding fallback default).
MODEL_FAST, MODEL_SMART = GEMINI_MODEL_FAST, GEMINI_MODEL_SMART

# ---- Database ----
DB_PATH = _path("JOB_AGENT_DB", "job_agent.db")
CHECKPOINT_DB_PATH = ROOT / "langgraph_checkpoints.sqlite"

# ---- Gmail ----
# Least-privilege: read-only for the Email Alert Parser, compose (draft-create) for
# the Outreach Composer. NEVER gmail.send.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]
GMAIL_CREDENTIALS_JSON = _path("GMAIL_CREDENTIALS_JSON", "credentials.json")
GMAIL_TOKEN_JSON = _path("GMAIL_TOKEN_JSON", "token.json")
# Owner identity — all sourced from .env. Defaults are neutral placeholders so the repo
# ships with NO personal data; each user fills these in their own .env.
OWNER_EMAIL = os.getenv("OWNER_EMAIL", "you@example.com")
OWNER_LINKEDIN = os.getenv("OWNER_LINKEDIN", "linkedin.com/in/your-handle")
OWNER_NAME = os.getenv("OWNER_NAME", "Your Name")
OWNER_FIRST_NAME = os.getenv("OWNER_FIRST_NAME", "Your")
OWNER_LAST_NAME = os.getenv("OWNER_LAST_NAME", "Name")
OWNER_PHONE = os.getenv("OWNER_PHONE", "")
OWNER_GITHUB = os.getenv("OWNER_GITHUB", "")
OWNER_LOCATION = os.getenv("OWNER_LOCATION", "")
# One-line description of your target profile — used by the Area Scout's web search and as
# context for classification. Tune this to your own search.
OWNER_PROFILE = os.getenv(
    "OWNER_PROFILE",
    "backend / full-stack software engineer (e.g. Go, Node.js, distributed systems, AI)")

EMAIL_ALERT_WINDOW_HOURS = int(os.getenv("EMAIL_ALERT_WINDOW_HOURS", "48"))
ALERT_SENDER_DOMAINS = [
    d.strip().lower()
    for d in os.getenv("ALERT_SENDER_DOMAINS", "naukri.com,indeed.com,cutshort.io").split(",")
    if d.strip()
]
# Map a sender domain to the jobs.source enum value.
ALERT_DOMAIN_TO_SOURCE = {
    "naukri.com": "naukri_alert",
    "indeed.com": "indeed_alert",
    "cutshort.io": "cutshort_alert",
}

# ---- Resume rendering ----
RESUME_RENDER_MODE = os.getenv("RESUME_RENDER_MODE", "pdflatex")
PDFLATEX_BIN = os.getenv("PDFLATEX_BIN", "pdflatex")
RESUME_GO_PDF = _path("RESUME_GO_PDF", "resume_go.pdf")
RESUME_NODE_PDF = _path("RESUME_NODE_PDF", "resume_node.pdf")
RESUME_GO_TEX = _path("RESUME_GO_TEX", "resume_go.tex")
RESUME_NODE_TEX = _path("RESUME_NODE_TEX", "resume_node.tex")
RESUME_OUTPUT_DIR = ROOT / "output" / "resumes"
RESUME_UPLOAD_DIR = ROOT / "data" / "resumes"   # user-uploaded base resumes (gitignored)

# ---- Playwright ----
PLAYWRIGHT_HEADED = os.getenv("PLAYWRIGHT_HEADED", "1") == "1"

# ---- Dashboard API ----
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

# ---- Seed ----
COMPANY_TRACKER_XLSX = _path("COMPANY_TRACKER_XLSX", "company_tracker.xlsx")

# ---- Job discovery filters (tune to your search via .env) ----
def _csv(name: str, default: str) -> list[str]:
    return [x.strip().lower() for x in os.getenv(name, default).split(",") if x.strip()]

# Role keywords: a posting must match one of these (whole-word) to be discovered.
KEYWORD_FILTERS = _csv("KEYWORD_FILTERS", "go,golang,node,backend,sde,agentic,llm")
# Locations you'll consider (matched against posting location; 'remote' always allowed).
LOCATION_FILTERS = _csv("LOCATION_FILTERS", "bengaluru,bangalore,hyderabad,pune,remote,india")
# Remote job boards (official public APIs) to poll. Options: remoteok, remotive, arbeitnow.
REMOTE_BOARDS = _csv("REMOTE_BOARDS", "remoteok,remotive,arbeitnow")


def ensure_dirs() -> None:
    RESUME_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESUME_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
