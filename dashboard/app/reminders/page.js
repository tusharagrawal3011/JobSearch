"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const BUCKETS = [
  { key: "now", label: "🔴 Do today", cls: "st-rejected" },
  { key: "soon", label: "🟡 This week", cls: "st-assessment" },
  { key: "waiting", label: "⚪ Waiting", cls: "st-applied" },
];

function Item({ it }) {
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState(null);
  const [copied, setCopied] = useState(false);

  async function followup() {
    setBusy(true);
    try {
      const r = await api.post(`/api/reminders/${it.id}/followup`, {});
      if (r.error) alert(r.error); else setDraft(r);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className={`card stripe st-${it.status}`}>
      <div className="row">
        <div>
          <strong>{it.action}</strong>
          <div className="small muted" style={{ marginTop: 2 }}>
            {it.company}{it.role ? ` · ${it.role}` : ""} <span className={`tag st-${it.status}`}>{it.status}</span>
          </div>
        </div>
        {it.can_followup && <button className="ghost" disabled={busy} onClick={followup}>{busy ? "Writing…" : "Draft follow-up"}</button>}
      </div>
      {draft && (
        <div style={{ marginTop: 10, borderTop: "1px dashed var(--border)", paddingTop: 10 }}>
          {draft.to && <div className="small muted">To: {draft.to}</div>}
          {draft.subject && <div className="small" style={{ marginTop: 2 }}><strong>Subject:</strong> {draft.subject}</div>}
          <div className="side" style={{ marginTop: 6 }}><div className="mono">{draft.body}</div></div>
          <div className="actions">
            <button className="ghost" onClick={() => { navigator.clipboard.writeText(draft.body || ""); setCopied(true); setTimeout(() => setCopied(false), 1200); }}>
              {copied ? "Copied ✓" : "Copy"}
            </button>
            {draft.gmail_draft_url && <a href={draft.gmail_draft_url} target="_blank" rel="noreferrer"><button className="ghost">Open Gmail draft ↗</button></a>}
          </div>
          {draft.note && <p className="small muted" style={{ marginTop: 4 }}>{draft.note}</p>}
        </div>
      )}
    </div>
  );
}

export default function Reminders() {
  const [data, setData] = useState(null);
  useEffect(() => { api.get("/api/reminders").then(setData).catch(() => setData({ items: [], counts: {} })); }, []);

  if (!data) return <p className="muted">Loading…</p>;
  const items = data.items || [];

  return (
    <>
      <h1>Reminders</h1>
      <p className="sub">What to do next on each application — follow-ups when things go quiet (after {data.followup_days} days), interviews to confirm, assessments to finish. Nothing sends automatically.</p>
      {items.length === 0
        ? <div className="empty">Nothing needs action. Refresh the tracker (My Applications) to pull the latest from Gmail.</div>
        : BUCKETS.map((b) => {
          const list = items.filter((i) => i.urgency === b.key);
          if (list.length === 0) return null;
          return (
            <div key={b.key}>
              <h3 style={{ fontSize: 15, marginTop: 22 }}>{b.label} <span className="muted small">({list.length})</span></h3>
              {list.map((it) => <Item key={it.id} it={it} />)}
            </div>
          );
        })}
    </>
  );
}
