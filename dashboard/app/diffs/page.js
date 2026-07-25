"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function Side({ title, children }) {
  return (
    <div className="side">
      <h4>{title}</h4>
      <div className="mono">{children}</div>
    </div>
  );
}

function DiffCard({ item, onDone }) {
  const [busy, setBusy] = useState(false);
  const d = item.diff || {};
  const summ = d.professional_summary || {};
  const skills = d.technical_skills || {};

  async function decide(action) {
    setBusy(true);
    try {
      await api.post(`/api/diffs/${item.resume_id}/decision`, { action });
      onDone(item.resume_id);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>{item.title}</strong> · <span className="muted">{item.company}</span>
          <div className="small muted" style={{ marginTop: 4 }}>
            <span className={`tag ${item.base_track}`}>{item.base_track} track</span>{" "}
            <span className={`tag ${item.stack_guess}`}>stack: {item.stack_guess}</span>{" "}
            <a href={item.jd_url} target="_blank" rel="noreferrer">JD ↗</a>
          </div>
        </div>
      </div>

      <label>Professional summary</label>
      <div className="diff">
        <Side title="Before"><span className="del">{summ.before || "—"}</span></Side>
        <Side title="After"><span className="add">{summ.after || "—"}</span></Side>
      </div>

      <label>Technical skills</label>
      <div className="diff">
        <Side title="Before"><span className="del">{fmt(skills.before)}</span></Side>
        <Side title="After"><span className="add">{fmt(skills.after)}</span></Side>
      </div>

      {(d.reordered_bullets || []).length > 0 && (
        <>
          <label>Bullet re-ordering / emphasis (Experience & Projects)</label>
          {d.reordered_bullets.map((b, i) => (
            <div key={i} className="checklist" style={{ marginBottom: 6 }}>
              <div className="small muted">{b.section} — {b.rationale}</div>
              <ol className="small">{(b.new_order || []).map((x, j) => <li key={j}>{x}</li>)}</ol>
            </div>
          ))}
        </>
      )}
      {d.notes && <p className="small muted">Note: {d.notes}</p>}

      <div className="actions">
        <button className="green" disabled={busy} onClick={() => decide("approve")}>Approve & render</button>
        <button className="red" disabled={busy} onClick={() => decide("reject")}>Reject</button>
        <span className="small muted" style={{ alignSelf: "center" }}>
          Edits: adjust in JSON via API, or approve then recompile the .tex.
        </span>
      </div>
    </div>
  );
}

function fmt(v) {
  if (Array.isArray(v)) return v.join(", ");
  return v || "—";
}

export default function Diffs() {
  const [items, setItems] = useState(null);
  const load = () => api.get("/api/diffs").then(setItems).catch(() => setItems([]));
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>Diff Approval queue</h1>
      <p className="sub">Human checkpoint #1 — approve the tailored resume diff before it is finalized. Only summary, skills, and bullet order/emphasis change; contact, education, and the Astrotech internship are never touched.</p>
      {items === null ? <p className="muted">Loading…</p>
        : items.length === 0 ? <div className="empty">No resume diffs waiting for approval.</div>
        : items.map((it) => <DiffCard key={it.resume_id} item={it} onDone={load} />)}
    </>
  );
}
