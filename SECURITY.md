# Security Policy

## Security model

This is a **local, single-user** tool. It runs on your machine, stores data in a local
SQLite file, and talks only to services you configure (your LLM provider and your own Gmail).

- **Everything is local.** The FastAPI backend binds to `127.0.0.1` only — it is **not** meant
  to be exposed to a network. Do not bind it to `0.0.0.0` or put it behind a public tunnel;
  it has no authentication because it assumes a single local user.
- **Least-privilege Gmail.** Only `gmail.readonly` (parse your alert emails) and `gmail.compose`
  (create outreach **drafts**) are requested. There is **no** `gmail.send` call anywhere in the
  codebase — the tool can never send email on your behalf.
- **Human-in-the-loop.** The agent never auto-submits an application and never sends a message.
  You approve the resume diff, click submit in the browser yourself, confirm each contact, and
  send outreach yourself.
- **Secrets never leave your machine.** `.env`, `credentials.json`, `token.json`, your resume,
  and the database are all gitignored. CI/commits are checked to contain no secrets.
- **Parameterized SQL.** All database access uses bound parameters; no user input is
  string-formatted into SQL.
- **LaTeX rendering** runs `pdflatex -no-shell-escape`, disabling shell execution from a
  crafted `.tex`.

## Threats to be aware of

- **Prompt injection.** Content the LLM reads (job-alert emails, careers pages, JDs) is
  untrusted and could try to steer the model. Blast radius is limited by design: outputs are
  structurally validated, stored via parameterized SQL, and every outward action (submit, send)
  requires a human. Still — review resume diffs and outreach drafts before acting on them.
- **URL fetching.** Job discovery fetches ATS APIs at fixed, known hostnames (only the slug is
  templated), which avoids arbitrary-host SSRF. The career-page reader opens a URL in a browser
  you control. Only add companies/URLs you trust.
- **Third-party ATS/LLM APIs.** You are sending data to whichever LLM provider and ATS
  endpoints you configure. Review their terms; prefer the local Ollama provider for full privacy.

## Reporting a vulnerability

If you find a security issue, please **do not open a public issue**. Instead, open a private
GitHub Security Advisory on this repository, or contact the maintainer directly. Include steps
to reproduce and the potential impact. We'll acknowledge and address it as quickly as we can.
