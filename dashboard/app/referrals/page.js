"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const SENIORITY = {
  founder: { label: "Founder", cls: "st-offer" },
  exec: { label: "Exec", cls: "st-offer" },
  manager: { label: "Manager", cls: "st-interview" },
  senior_engineer: { label: "Senior engineer", cls: "st-interview" },
  recruiter: { label: "Recruiter", cls: "st-assessment" },
  other: { label: "Contact", cls: "st-applied" },
};

const EMAIL = {
  found: { label: "email · public", cls: "em-ok" },
  inferred: { label: "email · inferred, verify", cls: "em-warn" },
  none: { label: "no public email", cls: "em-none" },
};

function Contact({ c, company, role }) {
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(null);
  const [copied, setCopied] = useState(false);
  const s = SENIORITY[c.seniority] || SENIORITY.other;
  const em = EMAIL[c.email_status] || EMAIL.none;

  async function makeDraft() {
    setBusy(true);
    try {
      const r = await api.post("/api/referrals/draft", { company, role, contact: c });
      if (r.error) alert(r.error); else setDraft(r);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className={`card stripe ${s.cls}`}>
      <div className="row">
        <div>
          <strong>{c.name}</strong> <span className={`tag ${s.cls}`}>{s.label}</span>
          <div className="small muted" style={{ marginTop: 2 }}>{c.title}</div>
          {c.why_them ? <div className="small" style={{ marginTop: 6 }}>{c.why_them}</div> : null}
          <div className="chips">
            <span className={`chip ${em.cls}`}>{em.label}</span>
            {c.email ? <span className="chip mono">{c.email}</span> : null}
            {c.public_profile_url
              ? <a className="chip link" href={c.public_profile_url} target="_blank" rel="noreferrer">profile ↗</a>
              : null}
          </div>
          {c.email_note ? <div className="small muted" style={{ marginTop: 4 }}>Email basis: {c.email_note}</div> : null}
          {c.source ? <div className="small muted" style={{ marginTop: 2 }}>Source: {c.source}</div> : null}
        </div>
        <button className="ghost" disabled={busy} onClick={makeDraft}>{busy ? "Writing…" : "Draft referral email"}</button>
      </div>
      {draft && (
        <div className="draft">
          <div className="small muted">To: {draft.to || c.name}{draft.email_status === "inferred" ? " (unverified)" : ""}</div>
          <div className="small" style={{ marginTop: 2 }}><strong>Subject:</strong> {draft.subject}</div>
          <div className="side" style={{ marginTop: 6 }}><div className="mono">{draft.body}</div></div>
          <div className="actions">
            <button className="ghost" onClick={() => { navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
            {draft.gmail_draft_url && <a href={draft.gmail_draft_url} target="_blank" rel="noreferrer"><button className="ghost">Open Gmail draft ↗</button></a>}
          </div>
          {draft.note && <p className="small muted" style={{ marginTop: 4 }}>{draft.note}</p>}
        </div>
      )}
      <style jsx>{`
        .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center; }
        .chip { font-size: 11px; padding: 3px 8px; border-radius: 20px; border: 1px solid var(--border); }
        .chip.link { text-decoration: none; color: var(--accent); }
        .em-ok { background: #12301f; color: #58d68a; border-color: #1c5236; }
        .em-warn { background: #33280f; color: #f4b45f; border-color: #5a4718; }
        .em-none { color: var(--muted); }
        .draft { margin-top: 10px; border-top: 1px dashed var(--border); padding-top: 10px; }
      `}</style>
    </div>
  );
}

export default function Referrals() {
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);

  // Prefill from ?company=&role= (e.g. deep-linked from My Applications).
  useEffect(() => {
    const q = new URLSearchParams(window.location.search);
    const c = q.get("company") || "";
    const r = q.get("role") || "";
    if (c) setCompany(c);
    if (r) setRole(r);
    if (c) find(c, r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function find(c = company, r = role, force = false) {
    if (!c.trim()) { alert("Enter a company."); return; }
    setBusy(true); setRes(null);
    try {
      const d = await api.post("/api/referrals/find", { company: c, role: r, force });
      setRes(d);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  const contacts = res?.contacts || [];

  return (
    <>
      <h1>Referrals</h1>
      <p className="sub">A warm referral beats a cold application. Enter a company and I&apos;ll find the best person to ask —
        a founder or CTO at a startup, a senior engineer, manager or recruiter at a bigger firm — from public sources only,
        then draft an honest referral email grounded in your profile. Nothing is sent automatically.</p>

      <div className="findbar">
        <input placeholder="Company *" value={company} onChange={(e) => setCompany(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && find()} />
        <input placeholder="Role (optional)" value={role} onChange={(e) => setRole(e.target.value)}
               onKeyDown={(e) => e.key === "Enter" && find()} />
        <button disabled={busy} onClick={() => find()}>{busy ? "Searching…" : "Find people"}</button>
      </div>

      {busy && <p className="muted" style={{ marginTop: 16 }}>Searching public sources…</p>}

      {res && !busy && (
        contacts.length === 0
          ? <div className="empty">No credible public contact found for {res.company}. Try adding the role, or search the company&apos;s team page directly.</div>
          : <>
            <div className="row" style={{ marginTop: 14, marginBottom: 4 }}>
              <h3 style={{ fontSize: 15 }}>{contacts.length} contact{contacts.length === 1 ? "" : "s"} at {res.company}</h3>
              {res.cached && <button className="ghost small" onClick={() => find(company, role, true)}>↻ Refresh</button>}
            </div>
            {contacts.map((c, i) => <Contact key={i} c={c} company={res.company} role={role} />)}
          </>
      )}

      <p className="small muted" style={{ marginTop: 22 }}>
        Contacts come from public pages (team/about, GitHub, personal sites, conference talks, public LinkedIn URLs) — no scraping.
        Emails marked <b>inferred</b> are the model&apos;s best guess at the company pattern, not confirmed — verify before sending.
      </p>

      <style jsx>{`
        .findbar { display: grid; grid-template-columns: 1.4fr 1fr auto; gap: 8px; }
        .findbar input { padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); color: inherit; font: inherit; }
        @media (max-width: 640px) { .findbar { grid-template-columns: 1fr; } }
      `}</style>
    </>
  );
}
