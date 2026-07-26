"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function CoverLetter({ jobId }) {
  const [open, setOpen] = useState(false);
  const [cl, setCl] = useState(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  async function toggle() {
    const next = !open; setOpen(next);
    if (next && cl === null) {
      try { setCl(await api.get(`/api/cover-letter/${jobId}`)); } catch { setCl({ body: "" }); }
    }
  }
  async function gen(force) {
    setBusy(true);
    try {
      const r = await api.post(`/api/cover-letter/${jobId}/generate${force ? "?force=true" : ""}`, {});
      if (r.error) alert(r.error); else setCl(r);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }
  async function save() {
    setBusy(true);
    try { await api.post(`/api/cover-letter/${jobId}/save`, { subject: cl.subject || "", body: cl.body || "" }); }
    catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }
  function copy() {
    navigator.clipboard.writeText(cl.body || ""); setCopied(true); setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div style={{ marginTop: 10, borderTop: "1px dashed var(--border)", paddingTop: 10 }}>
      <button className="ghost" style={{ fontSize: 12, padding: "4px 10px" }} onClick={toggle}>
        {open ? "Hide cover letter" : "📝 Cover letter"}
      </button>
      {open && (
        <div style={{ marginTop: 10 }}>
          {!cl || !cl.body ? (
            <button disabled={busy} onClick={() => gen(false)}>{busy ? "Writing…" : "Generate cover letter"}</button>
          ) : (
            <>
              <label>Subject</label>
              <input value={cl.subject || ""} onChange={(e) => setCl({ ...cl, subject: e.target.value })} />
              <label>Letter (editable · grounded in your résumé, no fabrication)</label>
              <textarea style={{ minHeight: 220 }} value={cl.body || ""} onChange={(e) => setCl({ ...cl, body: e.target.value })} />
              <div className="actions">
                <button className="ghost" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
                <button className="ghost" disabled={busy} onClick={save}>Save edits</button>
                <button className="ghost" disabled={busy} onClick={() => gen(true)}>{busy ? "…" : "Regenerate"}</button>
                {cl.status && <span className="small muted" style={{ alignSelf: "center" }}>{cl.status}</span>}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function ApplyCard({ job, onDone }) {
  const [busy, setBusy] = useState(false);
  const [ref, setRef] = useState("");

  async function launch() {
    setBusy(true);
    try {
      const r = await api.post(`/api/apply-queue/${job.job_id}/launch`, {});
      if (r.ok) {
        alert(`Headed browser closed. ${r.gaps?.length ? r.gaps.length + " screening question(s) were flagged." : "No screening gaps."}\nClick submit yourself, then Mark applied.`);
      } else { alert("Could not launch: " + (r.error || "unknown")); }
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  async function markApplied() {
    setBusy(true);
    try {
      await api.post(`/api/apply-queue/${job.job_id}/mark-applied`, { ats_confirmation_ref: ref });
      onDone(job.job_id);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>{job.title}</strong> · <span className="muted">{job.company}</span>
          <div className="small muted" style={{ marginTop: 4 }}>
            <span className={`tag ${job.base_track}`}>{job.base_track} résumé</span>{" "}
            <span className="tag src">{job.source}</span>{" "}
            {job.status === "flagged" && <span className="tag flag">needs your input</span>}{" "}
            <a href={job.jd_url} target="_blank" rel="noreferrer">JD ↗</a>
          </div>
          <div className="small muted" style={{ marginTop: 4 }}>PDF: {job.final_pdf_path || "not rendered"}</div>
        </div>
      </div>
      <div className="actions">
        <button disabled={busy} onClick={launch}>▶ Launch headed apply</button>
        <input style={{ maxWidth: 220 }} placeholder="ATS confirmation ref (optional)"
               value={ref} onChange={(e) => setRef(e.target.value)} />
        <button className="green" disabled={busy} onClick={markApplied}>✓ Mark applied</button>
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>
        The browser fills every field and stops at review — <strong>you click submit</strong> (Workday included).
      </p>
      <CoverLetter jobId={job.job_id} />
    </div>
  );
}

export default function Apply() {
  const [jobs, setJobs] = useState(null);
  const load = () => api.get("/api/apply-queue").then(setJobs).catch(() => setJobs([]));
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>Apply Queue</h1>
      <p className="sub">Human checkpoint #2 — one click launches the headed browser; the agent fills the form and stops. You submit each application yourself.</p>
      {jobs === null ? <p className="muted">Loading…</p>
        : jobs.length === 0 ? <div className="empty">No approved resumes ready to apply. Approve diffs first.</div>
        : jobs.map((j) => <ApplyCard key={j.job_id} job={j} onDone={load} />)}
    </>
  );
}
