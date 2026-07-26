"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function QList({ title, items }) {
  if (!items || items.length === 0) return null;
  return (
    <>
      <label style={{ marginTop: 10 }}>{title}</label>
      <ul className="checklist" style={{ margin: 0 }}>
        {items.map((q, i) => <li key={i} className="small">{q}</li>)}
      </ul>
    </>
  );
}

function PrepCard({ app }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);

  async function toggle() {
    const next = !open; setOpen(next);
    if (next && data === null && app.has_prep) {
      try { setData(await api.get(`/api/interview-prep/${app.id}`)); } catch { setData({ prep: {} }); }
    }
  }
  async function gen(force) {
    setBusy(true);
    try {
      const r = await api.post(`/api/interview-prep/${app.id}/generate${force ? "?force=true" : ""}`, {});
      if (r.error) alert(r.error); else setData(r);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  const p = data?.prep || {};
  const hasPrep = data && (data.brief || Object.keys(p).length > 0);

  return (
    <div className={`card stripe st-${app.status}`}>
      <div className="row">
        <div>
          <strong>{app.company}</strong> <span className="muted small">· {app.role || app.latest_subject}</span>
          <span className={`tag st-${app.status}`} style={{ marginLeft: 6 }}>{app.status}</span>
          {app.has_prep && <span className="tag st-offer" style={{ marginLeft: 4 }}>prep ready</span>}
        </div>
        <button className="ghost" disabled={busy} onClick={toggle}>{open ? "Hide" : app.has_prep ? "View prep" : "Prep for interview"}</button>
      </div>

      {open && (
        <div style={{ marginTop: 10 }}>
          {!hasPrep ? (
            <button disabled={busy} onClick={() => gen(false)}>{busy ? "Researching + writing…" : "🎓 Generate interview prep"}</button>
          ) : (
            <>
              {data.brief && <>
                <label>Company brief</label>
                <div className="side"><div className="mono" style={{ whiteSpace: "pre-wrap" }}>{data.brief}</div></div>
              </>}
              <QList title="Likely technical questions" items={p.technical_questions} />
              <QList title="Behavioral questions" items={p.behavioral_questions} />
              <QList title="They may probe these gaps" items={p.gap_questions} />
              <QList title="Your talking points (from your résumé)" items={p.talking_points} />
              <QList title="Sharp questions to ask them" items={p.questions_to_ask} />
              <div className="actions">
                <button className="ghost" disabled={busy} onClick={() => gen(true)}>{busy ? "…" : "Regenerate"}</button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function InterviewPrep() {
  const [apps, setApps] = useState(null);
  useEffect(() => { api.get("/api/interview-prep").then(setApps).catch(() => setApps([])); }, []);

  return (
    <>
      <h1>Interview Prep</h1>
      <p className="sub">For each interview, get a company research brief, likely questions tuned to the role and your résumé gaps, talking points from your real experience, and sharp questions to ask them.</p>
      {apps === null ? <p className="muted">Loading…</p>
        : apps.length === 0 ? <div className="empty">No interviews detected yet. When the tracker (My Applications) finds an interview, it shows up here.</div>
        : apps.map((a) => <PrepCard key={a.id} app={a} />)}
    </>
  );
}
