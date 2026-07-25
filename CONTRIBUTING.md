# Contributing

Thanks for your interest! This project follows a simple protected-`main` workflow.

## Branches

- **`main`** — stable, protected. No direct pushes or merges. Updated only via reviewed pull
  requests from `dev`.
- **`dev`** — the active integration branch. All work lands here first.
- **`feature/*` / `fix/*`** — your own working branches, created off `dev`.

## Workflow

1. **Fork** the repo (or, if you're a collaborator, create a branch — never commit to `main`).
2. Branch off `dev`:
   ```bash
   git checkout dev
   git pull origin dev
   git checkout -b feature/your-thing
   ```
3. Make your changes with clear, focused commits.
4. Push your branch and open a **pull request into `dev`** (not `main`).
5. A maintainer reviews and merges into `dev`. Releases are promoted `dev` → `main` by the
   maintainer via a reviewed PR.

## Ground rules

Please keep the project's core principles intact in any contribution:

- **Legitimate sources only** — public ATS APIs and the user's own inbox. No scraping of
  LinkedIn/Indeed/Naukri or other job portals.
- **Human-in-the-loop** — never auto-submit an application; never send an email or message
  (outreach stays draft-only).
- **No secrets or personal data** in commits — everything personal comes from `.env`, which is
  gitignored. Double-check `git status` before committing.

## Local setup

See the [README](README.md) "Quick start" section.

## Style

- Python: match the existing style; keep functions small and readable.
- Keep prompts and provider logic behind the existing abstractions (`backend/llm`,
  `backend/ats`) so new providers are easy to add.
