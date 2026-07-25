# Job Application Agent

A **local, human-in-the-loop** job-search assistant. It watches company ATS boards and your
own job-alert emails, tailors your resume to each role, walks you to the final "submit" screen
of an application, reconstructs the status of everything you've applied to from your inbox, and
drafts (never sends) outreach for you to review.

Everything runs on **your machine**. Your resume, keys, and application history never leave it.

> ⚠️ Read [DISCLAIMER.md](DISCLAIMER.md) — this tool uses **legitimate sources only** (public
> ATS APIs + your own inbox) and **never scrapes** LinkedIn/Indeed/Naukri.

---

## Why it's safe by design

1. **Legitimate sources only** — job discovery uses the public JSON APIs that ATS platforms
   publish themselves (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, BambooHR)
   plus job-alert emails delivered to *your* inbox. No portal scraping.
2. **Four human checkpoints** — you approve the tailored resume, you click submit on every
   application, you confirm each contact, you send every message. The agents never act
   outward on your behalf.
3. **Outreach is draft-only** — it creates Gmail **drafts** via the API; there is **no** send
   call anywhere in the code.
4. **Local & private** — SQLite on disk, LLM via your own key or a local model. Nothing is
   hosted.

## Features

- **Discovery** across 7 ATS platforms + your Naukri/Indeed/Cutshort (and any) email alerts
- **Area Scout** — web-search any location ("HSR Layout, Bangalore") for companies hiring your
  profile, auto-added with ATS detection
- **Career-page reader** — for companies with no public API, reads the employer's own careers page
- **JD analysis** — classifies each role and routes it to the matching resume track
- **Resume tailoring** — proposes a *diff only* (summary, skills, bullet order) of your real
  resume, for your approval; renders via local LaTeX or Overleaf
- **Assisted apply** — a headed browser fills the ATS form and stops at the review screen
- **Application tracker** — reconstructs every application's live status (applied / assessment /
  interview / offer / rejected) from your Gmail, with a dashboard
- **Contact discovery + outreach drafts** — public-source contact + Gmail draft, draft-only
- **Pluggable LLM chain** — Gemini / Ollama (local) / Anthropic / OpenAI, with retry + fallback

## Architecture

```
ATS APIs ─┐
Emails ───┼─▶ Discovery ─▶ JD Analyzer ─▶ Resume Tailor ─▶ [you approve]
Scout ────┘                                                     │
                                        ┌──────────────────────┘
                                        ▼
                        Application Submission (headed browser) ─▶ [you submit]
                                        │
                                        ▼
                        Contact Discovery ─▶ Outreach (Gmail drafts) ─▶ [you send]

           Application Tracker (reads your Gmail) ─▶ Dashboard
```

- **Backend:** Python + LangChain + LangGraph, SQLite, FastAPI (`backend/`)
- **Dashboard:** Next.js (`dashboard/`)
- **Browser automation:** Playwright (headed)

---

## Quick start

### Prerequisites
- Python 3.11+ and Node.js 18+
- (Optional) [Ollama](https://ollama.com) for a free local LLM, and/or a
  [Gemini API key](https://aistudio.google.com/apikey) (free tier is plenty for personal use)
- (Optional) A LaTeX install (MiKTeX/TeX Live) for automatic PDF rendering — or use Overleaf

### 1. Clone & install
```bash
git clone <your-fork-url> job-application-agent
cd job-application-agent

python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cd dashboard && npm install && cd ..
```

### 2. Configure
```bash
cp .env.example .env
cp dashboard/.env.local.example dashboard/.env.local
```
Edit `.env` and fill in:
- `GEMINI_API_KEY` (or set `LLM_CHAIN=ollama` to run fully local)
- `OWNER_*` — your name, email, LinkedIn, GitHub, phone, location
- `OWNER_PROFILE`, `KEYWORD_FILTERS`, `LOCATION_FILTERS` — tune discovery to your search

### 3. Add your resume
Copy the template and replace with your content (your real files are gitignored):
```bash
cp resume_go.sample.tex resume_go.tex
cp resume_go.sample.tex resume_node.tex   # a second variant, e.g. emphasizing a different stack
```
The tailor only edits the summary, skills, and bullet **order** — it never invents experience.
Set `RESUME_RENDER_MODE=manual` (compile on Overleaf) or `pdflatex` (local LaTeX install).

### 4. Gmail access (for email parsing + outreach drafts)
1. In [Google Cloud Console](https://console.cloud.google.com): create a project → enable the
   **Gmail API** → **OAuth consent screen** (External, add yourself as a Test user) →
   **Credentials → OAuth client ID → Desktop app** → download the JSON.
2. Save it as `credentials.json` in the repo root. First run opens a browser for consent once.
   Scopes: `gmail.readonly` + `gmail.compose` — **never** send.

### 5. Set up job alerts (one-time, per portal)
On Naukri / Indeed / Cutshort (and LinkedIn, Wellfound, etc.), create job alerts with your
keywords + locations so they email your inbox. The parser reads mail sent to you.

### 6. Initialize & run
```bash
python run_pipeline.py --init         # create the DB + seed sample companies
python run_pipeline.py                # full run: discover → analyze → tailor → tracker → report
```

### 7. Open the dashboard (two terminals)
```bash
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000   # terminal 1: API
cd dashboard && npm run dev                                  # terminal 2: dashboard → localhost:3000
```

---

## Everyday use

**Pipeline (cron or manual):**
```bash
python run_pipeline.py                 # everything
python run_pipeline.py --discover      # ATS + email discovery only
python run_pipeline.py --tracker       # refresh application statuses from Gmail
python run_pipeline.py --scout "HSR Layout, Bangalore"   # find + add companies in an area
python run_pipeline.py --report        # print the daily summary
```

**Dashboard pages:** My Applications (tracker) · Diff Approval · Apply Queue · Screening Q&A ·
Outreach · Add Company (+ Scout) · Daily Digest.

**The loop:** the pipeline discovers and tailors → you approve resume diffs → work the Apply
Queue (one click launches the browser; you submit) → confirm discovered contacts → review and
send the drafted outreach yourself.

## Adapting it to your profile

It ships tuned for a two-track backend profile (labelled `go` / `node`), but it's configurable:
- Set `OWNER_PROFILE`, `KEYWORD_FILTERS`, `LOCATION_FILTERS` in `.env`.
- Provide two resume variants (`resume_go.tex`, `resume_node.tex`) — the classifier routes each
  job to the better-fitting one. Use them for any two emphases (e.g. backend vs. full-stack).
- Add more alert sources by appending sender domains to `ALERT_SENDER_DOMAINS`.
- Register more LLM/ATS providers in `backend/llm/providers.py` / `backend/ats/detector.py`.

## Configuration reference

| Key | What |
|---|---|
| `LLM_CHAIN` | Ordered provider fallback, e.g. `gemini,ollama` |
| `GEMINI_API_KEY` | Gemini key (free tier covers personal use) |
| `OWNER_*` | Your identity, used to fill application forms + outreach |
| `OWNER_PROFILE` | One-line target-role description for scout + classifier |
| `KEYWORD_FILTERS` / `LOCATION_FILTERS` | Discovery filters |
| `ALERT_SENDER_DOMAINS` | Which senders the email parser reads |
| `RESUME_RENDER_MODE` | `manual` (Overleaf) or `pdflatex` (local LaTeX) |
| `GMAIL_CREDENTIALS_JSON` | Path to your Gmail OAuth client secret |

## Roadmap

- Onboarding via Google OAuth login + resume upload that **auto-derives your target companies**
  and profile (so setup is just "log in + upload resume")
- More ATS providers and remote-board public feeds
- Per-provider tier routing (e.g. local for bulk, cloud for tailoring)

## Contributing

Issues and PRs welcome. Please keep the "legitimate sources only, human-in-the-loop, draft-only"
principles intact.

## License

[MIT](LICENSE)
