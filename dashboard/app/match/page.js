"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function scoreClass(s) { return s >= 75 ? "hi" : s >= 50 ? "mid" : "lo"; }

function MatchCard({ job, onOptimized }) {
  const [data, setData] = useState(job.score != null ? { score: job.score } : null);
  const [busy, setBusy] = useState(false);
  const [opt, setOpt] = useState(null);

  async function check(force = false) {
    setBusy(true);
    try {
      const r = await api.get(`/api/match/${job.job_id}${force ? "?force=true" : ""}`);
      if (r.error) alert(r.error); else setData(r);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  async function optimize() {
    setBusy(true); setOpt(null);
    try {
      const r = await api.post(`/api/match/${job.job_id}/optimize`, { keywords: data.missing || [] });
      if (r.error) { alert(r.error); } else { setOpt(r); onOptimized && onOptimized(); }
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  const full = data && data.matched;   // full result (not just a cached number)
  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>{job.title}</strong> <span className="muted small">· {job.company}</span>
          {job.stack_guess && <span className={`tag ${job.stack_guess}`} style={{ marginLeft: 6 }}>{job.stack_guess}</span>}
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {data && data.score != null && <div className={`score ${scoreClass(data.score)}`}>{data.score}</div>}
          <button className="ghost" disabled={busy} onClick={() => check(!!full)}>
            {busy ? "…" : full ? "Recheck" : "Check match"}
          </button>
        </div>
      </div>

      {full && (
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
              {opt.skipped_no_evidence?.length > 0 && <div className="small pill-warn" style={{ marginTop: 4 }}>⚠ Not added (no evidence in your résumé — add only if true): {opt.skipped_no_evidence.join(", ")}</div>}
            </div>
          )}
        </>
      )}
    </div>
  );
}

export default function Match() {
  const [jobs, setJobs] = useState(null);
  const load = () => api.get("/api/match").then(setJobs).catch(() => setJobs([]));
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>JD Match</h1>
      <p className="sub">For any job, see how your résumé scores against the JD, which keywords match, which are missing — then generate a résumé that weaves in the missing ones (truthfully — it won&apos;t fabricate skills you don&apos;t have).</p>
      {jobs === null ? <p className="muted">Loading…</p>
        : jobs.length === 0 ? <div className="empty">No jobs with a JD yet. Run discovery first.</div>
        : jobs.map((j) => <MatchCard key={j.job_id} job={j} onOptimized={load} />)}
    </>
  );
}
