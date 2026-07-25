# Disclaimer & Responsible Use

This project is a **personal, local** job-search assistant. Please use it responsibly.

- **Legitimate data sources only.** Job discovery uses the **public JSON APIs** that ATS
  platforms (Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Recruitee, BambooHR)
  publish themselves, and **job-alert emails delivered to your own inbox**. The optional
  career-page reader reads a single employer's **own public careers page**. The project does
  **not** scrape LinkedIn, Indeed, Naukri, or other job portals — doing so violates their
  Terms of Service and can get your accounts banned.

- **You stay in control.** The system stops at four human checkpoints and never acts on your
  behalf outward: it never auto-submits an application, and it never sends an email or message
  (outreach is created as Gmail **drafts** only — there is no `send` call anywhere).

- **Respect rate limits and ToS.** Poll company boards at reasonable intervals. You are
  responsible for how you configure and run this tool.

- **No warranty.** Provided "as is" under the MIT License. Statuses inferred from your inbox
  are best-effort and may be imperfect — verify anything important yourself.

- **Your data stays yours.** Everything runs locally. Your resume, API keys, Gmail token, and
  application database are gitignored and never leave your machine.
