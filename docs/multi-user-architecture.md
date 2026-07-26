# Design: Multi-user & hosted architecture

**Status:** Draft / for discussion · **Author:** Tushar Agrawal
**Goal:** Let each user sign up, log in (JWT), and have their **own** jobs, resumes,
applications and tracker — without breaking the working local single-user tool.

---

## 1. Where we are today

The app is **single-user and local**:

- One SQLite file (`job_agent.db`) on the user's machine. **No `users` table, no `user_id`
  on any row** — every table implicitly belongs to "the one user."
- Identity comes from `.env` (`OWNER_*`), not the database.
- Secrets live on disk: `.env` (LLM key), `credentials.json` + `token.json` (Gmail).
- Several features are **inherently local**:
  - **Apply flow** = a *headed Playwright browser* opened on the user's own screen.
  - **Gmail** = the user's own OAuth token on disk.
  - **LLM** = the user's own key, or a **local Ollama** model.

Adding "accounts" touches all of this. The honest framing: **auth is the easy 10%;
per-user data isolation and the local-only features are the hard 90%.**

## 2. Two very different target models

| | **A. Local multi-profile** | **B. Hosted SaaS** |
|---|---|---|
| Runs on | The user's machine | Your server |
| Users | One person, multiple "profiles" | Many remote users |
| Auth | A light gate (optional) | Required, real |
| Data | Local SQLite, `user_id`-scoped | Server DB (Postgres), `user_id`-scoped, backups |
| Gmail | Local token per profile | **Per-user OAuth → Google restricted-scope verification** |
| LLM | Local Ollama or user's key | Cloud key (your cost) or user-supplied |
| **Apply autofill** | Local Playwright (works) | **Playwright can't open on a remote screen** → needs a browser extension |
| Effort | Moderate | Large (a real product) |

**These are different products.** "Signup/login with JWT so each user can track" points at
**B**, but B changes the core mechanics of the apply flow and Gmail. Decide the target before
writing table migrations.

## 3. Authentication (the straightforward part)

### Data
```sql
users (
  id            INTEGER PRIMARY KEY,
  email         TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,      -- bcrypt (passlib)
  name          TEXT,
  created_at    TEXT
)
```

### Backend (`backend/auth.py`)
- Hash with **bcrypt** (`passlib[bcrypt]`). Never store plaintext.
- Issue a **JWT access token** (HS256) signed with `JWT_SECRET` from `.env`
  (fail loudly if unset in production). Short expiry (e.g. 12h); optional refresh token later.
- `get_current_user()` FastAPI dependency: read `Authorization: Bearer <jwt>`, verify, load user.
- Endpoints: `POST /api/auth/signup`, `POST /api/auth/login`, `GET /api/auth/me`.

### Frontend
- `/login` and `/signup` pages; store the JWT in memory + `localStorage`.
- API client sends the `Authorization` header; a guard redirects to `/login` when absent/expired.
- Show the signed-in email + a logout button in the sidebar.

### Security notes
- HTTPS is mandatory once hosted (JWT in the clear = account takeover).
- `JWT_SECRET` must be a strong random value, rotated carefully.
- Rate-limit `login`/`signup`; lock out on repeated failures.
- Consider `httpOnly` cookies over `localStorage` to reduce XSS token theft (trade-off: CSRF).

## 4. Per-user data isolation (the big part)

Auth is meaningless for "track their own data" unless **every** user-owned row carries a
`user_id` and **every** query filters by it.

**Tables that need `user_id`:** `jobs`, `resumes`, `base_resumes`, `applications`, `contacts`,
`outreach_drafts`, `screening_answers`, `tracked_applications`, `tracked_events`,
`tracker_volume`, `agent_runs`. (`companies` is arguably shared reference data — but a user's
*target list* is personal, so likely per-user too, or a shared catalog + per-user "tracked" join.)

**Enforcement strategy (pick one, be strict):**
1. **Thread `user_id` everywhere** — every agent/query takes `user_id` and filters. Explicit,
   verbose, but auditable. Highest risk is *forgetting* a filter (data leak between users).
2. **A scoped connection/helper** — a thin data-access layer that injects `WHERE user_id=?`
   automatically, so a forgotten filter can't happen. Recommended.

**Migration:** add the columns, **backfill existing rows to a default/first user**, then make
`user_id` NOT NULL. This is a large, careful change across ~12 tables and all agent code — it
should be its own phase with thorough tests (a "user A cannot see user B's rows" test suite).

## 5. Per-user secrets (the genuinely hard part)

Each user needs their own **Gmail token** and **LLM access**. On a shared server:

- **Gmail:** every user runs OAuth against **one shared Google app**. `gmail.readonly` /
  `gmail.compose` are **restricted scopes** → the app needs **Google's security assessment
  (CASA, annual, paid)**. Until verified: **capped at 100 users + an "unverified app" screen.**
  Tokens must be **encrypted at rest**, per user, and refreshed server-side. This is a real
  compliance + security burden — you become a data processor of people's inboxes.
- **LLM:** either **users bring their own key** (stored encrypted per user) or **you provide a
  shared key** (you pay; needs quotas/limits per user). **Local Ollama does not work per-user on
  a shared server** — hosted = cloud LLM only.

**Recommendation:** store per-user secrets encrypted (e.g. a KMS or a symmetric key from env +
per-row nonce), never in plaintext, never in logs. Treat this phase as security-critical.

## 6. The apply-flow problem (and the Simplify.jobs lesson)

The current apply flow opens a **headed Playwright browser on the user's screen**. On a hosted
server there *is* no user screen. Options:

1. **Browser extension** (what **Simplify.jobs** does) — autofill runs in the *user's own*
   browser as they view the application. Solves the "remote screen" problem cleanly, keeps the
   human in the loop, and needs no server-side browser. **Recommended for a hosted apply story.**
2. **Hybrid** — host discovery/tracking/tailoring; keep apply **local** via a small companion
   app or the extension. Pragmatic middle path.
3. **Remote browser streaming** (server Playwright + noVNC/CDP to the user) — heavy, fragile,
   expensive. Not recommended.

So a hosted version likely **re-implements apply as an extension**, and the server does
discovery, tailoring, tracking, and outreach drafting.

## 7. Recommended phased plan

- **Phase 1 — Auth foundation (local).** `users` + JWT + signup/login pages + a login gate.
  Data still shared. Low risk, unblocks everything. *(This is the "Auth foundation first" option.)*
- **Phase 2 — Per-user data isolation.** `user_id` everywhere + scoped data layer + isolation
  tests + backfill migration. Big, careful, well-tested.
- **Phase 3 — Per-user secrets + hosting.** Encrypted per-user Gmail tokens + LLM keys; deploy
  to a server with Postgres + HTTPS; begin Google OAuth verification.
- **Phase 4 — Apply as a browser extension.** Move autofill off server Playwright into the
  user's browser (Simplify-style).

## 8. Honest recommendation

For a **personal, open-source, local** tool, full SaaS (Phases 3–4) is a large commitment with
real cost (Google verification, hosting, LLM bills, security/compliance). Two sane paths:

- **Stay local, add Phase 1 + 2** so *you* can keep multiple profiles/searches cleanly — most of
  the "each user tracks their own data" value, none of the hosting/compliance burden.
- **Commit to hosted** — then plan Phases 1→4 as a real product, starting with auth + isolation,
  and accept the Gmail-verification and apply-extension work as the price of multi-user.

**Suggested next step:** build **Phase 1** (it's useful either way and reversible), and defer the
Phase 2 migration until the local-vs-hosted decision is made.

## 9. Open decisions

- [ ] Local multi-profile, or hosted SaaS? (Determines everything below.)
- [ ] If hosted: who pays for the LLM — users' keys or a shared key with quotas?
- [ ] Accept Google's restricted-scope verification (cost/time) for Gmail, or drop Gmail features
      in the hosted version?
- [ ] Is `companies` shared reference data or per-user?
- [ ] Cookie (`httpOnly`) vs `localStorage` for the JWT?
