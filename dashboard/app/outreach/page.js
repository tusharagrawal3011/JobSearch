"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function Copy({ text }) {
  const [done, setDone] = useState(false);
  return (
    <button className="ghost" onClick={() => { navigator.clipboard.writeText(text || ""); setDone(true); setTimeout(() => setDone(false), 1200); }}>
      {done ? "Copied ✓" : "Copy"}
    </button>
  );
}

function ContactCard({ c, onVerified }) {
  const [busy, setBusy] = useState(false);
  async function verify() {
    setBusy(true);
    try { await api.post(`/api/contacts/${c.id}/verify`, { verified: true }); onVerified(); }
    catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }
  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>{c.name}</strong> <span className="muted">· {c.role_guess || "role unknown"} · {c.company}</span>
          <div className="small"><a href={c.public_profile_url} target="_blank" rel="noreferrer">{c.public_profile_url}</a></div>
          <div className="small muted">source: {c.source}</div>
        </div>
        <button className="green" disabled={busy} onClick={verify}>Confirm & draft outreach</button>
      </div>
    </div>
  );
}

function DraftCard({ d }) {
  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>{d.contact_name}</strong> <span className="muted">· {d.company} · {d.title}</span>
          <div className="small muted">{d.channel === "email" ? "Email draft" : "LinkedIn message"} · <span className="tag">draft only — nothing sends automatically</span></div>
        </div>
      </div>
      {d.channel === "email" && d.subject_line && <div className="small" style={{ marginTop: 8 }}><strong>Subject:</strong> {d.subject_line}</div>}
      <div className="side" style={{ marginTop: 8 }}><div className="mono">{d.draft_text}</div></div>
      <div className="actions">
        <Copy text={d.channel === "email" ? `Subject: ${d.subject_line}\n\n${d.draft_text}` : d.draft_text} />
        {d.gmail_draft_url && <a href={d.gmail_draft_url} target="_blank" rel="noreferrer"><button className="ghost">Open Gmail draft ↗</button></a>}
        {d.channel === "linkedin" && <span className="small muted" style={{ alignSelf: "center" }}>Paste into LinkedIn and send yourself.</span>}
      </div>
    </div>
  );
}

export default function Outreach() {
  const [drafts, setDrafts] = useState(null);
  const [contacts, setContacts] = useState([]);
  const load = () => {
    api.get("/api/outreach").then(setDrafts).catch(() => setDrafts([]));
    api.get("/api/contacts").then((cs) => setContacts(cs.filter((c) => !c.verified_by_human))).catch(() => setContacts([]));
  };
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>Outreach queue</h1>
      <p className="sub">Draft-only, always. The Composer creates Gmail drafts and LinkedIn text — <strong>you send everything yourself</strong>.</p>

      {contacts.length > 0 && (
        <>
          <h3 style={{ fontSize: 15 }}>Contacts awaiting your confirmation</h3>
          {contacts.map((c) => <ContactCard key={c.id} c={c} onVerified={load} />)}
        </>
      )}

      <h3 style={{ fontSize: 15, marginTop: 24 }}>Drafts</h3>
      {drafts === null ? <p className="muted">Loading…</p>
        : drafts.length === 0 ? <div className="empty">No outreach drafts yet. Confirm a discovered contact to generate drafts.</div>
        : drafts.map((d) => <DraftCard key={d.id} d={d} />)}
    </>
  );
}
