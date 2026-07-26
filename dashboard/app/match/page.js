"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function scoreClass(s) { return s >= 75 ? "hi" : s >= 50 ? "mid" : "lo"; }

function MatchCard({ job, onOptimized }) {
  const [data, setData] = useState(job);   // has score + score_type from the ranked list
  const [busy, setBusy] = useState(false);
  const [opt, setOpt] = useState(null);
  const scored = data.score_type === "ai" && data.matched;   // full AI detail loaded

  async function check(force) {
    setBusy(true);
    try {
      const r = await api.get(`/api/match/${job.job_id}${force ? "?force=true" : ""}`);
      if (r.error) alert(r.error); else setData({ ...data, ...r, score_type: "ai" });
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  async function optimize() {
    setBusy(true); setOpt(null);
    try {
      const r = await api.post(`/api/match/${job.job_id}/optimize`, { keywords: data.missing || [] });
      if (r.error) alert(r.error); else { setOpt(r); onOptimized && onOptimized(); }
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>{job.title}</strong> <span className="muted small">· {job.company}</span>
          {job.stack_guess && <span className={`tag ${job.stack_guess}`} style={{ marginLeft: 6 }}>{job.stack_guess}</span>}
          {job.seniority && job.seniority !== "unknown" && <span className="tag" style={{ marginLeft: 4 }}>{job.seniority}</span>}
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div className={`score ${scoreClass(data.score)} ${data.score_type === "ai" ? "" : "est"}`}
               title={data.score_type === "ai" ? "AI match score" : "estimated — click Check for a precise AI score"}>
            {data.score}
          </div>
          <button className="ghost" disabled={busy} onClick={() => check(scored)}>
            {busy ? "…" : scored ? "Recheck" : "Check match"}
          </button>
        </div>
      </div>

      {scored && (
        <>
          {data.summary && <p className="small muted" style={{ marginTop: 8 }}>{data.summary}</p>}
          {data.matched?.length > 0 && <>
            <label style={{ marginTop: 8 }}>Matched ({data.matched.length})</label>
            <div className="kws">{data.matched.map((k, i) => <span key={i} className="kw match">{k}</span>)}</div>
          </>}
          {data.missing?.length > 0 && <>
            <label style={{ marginTop: 8 }}>Missing keywords ({data.missing.length})</label>
            <div className="kws">{data.missing.map((k, i) => <span key={i} className="kw miss">{k}</span>)}</div>
            <div className="actions">
              <button disabled={busy} onClick={optimize}>{busy ? "Optimizing…" : "✨ Add these keywords → updated résumé"}</button>
            </div>
          </>}
          {opt && (
            <div className="checklist" style={{ marginTop: 12 }}>
              <div><strong>Updated résumé created</strong> (in Diff Approval &amp; Resumes → per-job view).</div>
              {opt.added_keywords?.length > 0 && <div className="small" style={{ marginTop: 4 }}>✅ Added (truthful): {opt.added_keywords.join(", ")}</div>}
              {opt.skipped_no_evidence?.length > 0 && <div className="small pill-warn" style={{ marginTop: 4 }}>⚠ Not added (no evidence — add only if true): {opt.skipped_no_evidence.join(", ")}</div>}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function Match() {
  const [jobs, setJobs] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/api/match?limit=100").then(setJobs).catch(() => setJobs([]));
  useEffect(() => { load(); }, []);

  async function sharpen() {
    setBusy(true);
    try { const r = await api.post("/api/match/score-batch?limit=20", {}); await load();
      alert(`AI-scored ${r.scored} more job(s). ${r.remaining_unscored} still estimated.`);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  const estimated = (jobs || []).filter((j) => j.score_type !== "ai").length;
  return (
    <>
      <h1>Best Matches</h1>
      <p className="sub">Your jobs ranked by how well your résumé fits each JD. Scores start as an instant estimate; AI-scoring sharpens them and unlocks the keyword gaps + one-click optimize.</p>
      {jobs && jobs.length > 0 && (
        <div className="toolbar">
          <span className="small muted">{jobs.length} jobs · {jobs.length - estimated} AI-scored · {estimated} estimated</span>
          {estimated > 0 && <button disabled={busy} onClick={sharpen}>{busy ? "AI-scoring…" : "⚡ Sharpen ranking (AI-score top 20)"}</button>}
        </div>
      )}
      {jobs === null ? <p className="muted">Loading…</p>
        : jobs.length === 0 ? <div className="empty">No analyzed jobs yet. Run discovery + analysis first.</div>
        : jobs.map((j) => <MatchCard key={j.job_id} job={j} onOptimized={load} />)}
    </>
  );
}
