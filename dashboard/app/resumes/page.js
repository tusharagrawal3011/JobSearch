"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function GmailCard() {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/api/gmail/status").then(setSt).catch(() => setSt({}));
  useEffect(() => { load(); }, []);

  async function connect() {
    setBusy(true);
    try {
      const r = await api.post("/api/gmail/connect", {});
      if (r.ok) alert(`Connected as ${r.email}`);
      else alert("Could not connect: " + (r.error || "unknown"));
      load();
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  if (!st) return null;
  return (
    <div className="card">
      <div className="row">
        <div>
          <strong>Gmail</strong>{" "}
          {st.connected
            ? <span className="tag st-offer">connected</span>
            : <span className="tag flag">not connected</span>}
          <p className="small muted" style={{ marginTop: 4, maxWidth: 620 }}>
            Optional. Enables email-alert parsing, the application tracker, and auto-created outreach drafts.
            Discovery &amp; tailoring work without it.
            {!st.credentials && " Add your Google OAuth credentials.json to the project root to enable the button."}
          </p>
        </div>
        {!st.connected && (
          <button disabled={busy || !st.credentials} onClick={connect}>
            {busy ? "Opening consent…" : "Connect Gmail"}
          </button>
        )}
      </div>
    </div>
  );
}

function UploadCard({ onDone }) {
  const [track, setTrack] = useState("go");
  const [tex, setTex] = useState(null);
  const [pdf, setPdf] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!tex && !pdf) { alert("Choose a .tex and/or .pdf file"); return; }
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("track", track);
      if (tex) fd.append("tex", tex);
      if (pdf) fd.append("pdf", pdf);
      await api.upload("/api/resumes/upload", fd);
      setTex(null); setPdf(null); onDone();
      alert("Uploaded — it's now the active base resume for the " + track + " track.");
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="card">
      <strong>Upload a base resume</strong>
      <p className="small muted" style={{ marginTop: 2 }}>
        Upload the LaTeX <code>.tex</code> (enables real tailoring + side-by-side view) and/or a compiled
        <code>.pdf</code>. It becomes the active resume for that track. The tailor only edits the summary,
        skills, and bullet order — never your experience.
      </p>
      <label>Track</label>
      <select value={track} onChange={(e) => setTrack(e.target.value)} style={{ width: "auto" }}>
        <option value="go">go</option>
        <option value="node">node</option>
      </select>
      <label>LaTeX source (.tex)</label>
      <input type="file" accept=".tex,text/plain" onChange={(e) => setTex(e.target.files[0])} />
      <label>Compiled PDF (.pdf, optional)</label>
      <input type="file" accept="application/pdf" onChange={(e) => setPdf(e.target.files[0])} />
      <div className="actions">
        <button disabled={busy} onClick={submit}>{busy ? "Uploading…" : "Upload resume"}</button>
      </div>
    </div>
  );
}

function TailoredViewer() {
  const [list, setList] = useState([]);
  const [sel, setSel] = useState(null);
  const [view, setView] = useState(null);

  useEffect(() => { api.get("/api/resumes/tailored").then(setList).catch(() => setList([])); }, []);

  async function open(jobId) {
    setSel(jobId); setView(null);
    try { setView(await api.get(`/api/resumes/job/${jobId}`)); }
    catch (e) { alert("Error: " + e.message); }
  }

  return (
    <div className="card">
      <strong>Resume per job</strong>
      <p className="small muted" style={{ marginTop: 2 }}>See your original resume next to the version tailored for a specific JD.</p>
      {list.length === 0
        ? <div className="empty" style={{ marginTop: 10 }}>No tailored resumes yet. Approve a diff in the Diff Approval queue.</div>
        : (
          <select style={{ marginTop: 10 }} value={sel || ""} onChange={(e) => open(Number(e.target.value))}>
            <option value="" disabled>Choose a job…</option>
            {list.map((j) => (
              <option key={j.job_id} value={j.job_id}>
                {j.company} — {j.title} ({j.base_track}{j.has_tailored ? "" : " · not tailored"})
              </option>
            ))}
          </select>
        )}
      {view && (
        <div className="diff" style={{ marginTop: 12 }}>
          <div className="side">
            <h4>Original ({view.track}{view.has_uploaded_base ? " · uploaded" : " · file"})</h4>
            <div className="mono" style={{ maxHeight: 420, overflow: "auto" }}>{view.base_tex || "(no base resume — upload one above)"}</div>
          </div>
          <div className="side">
            <h4>Tailored{view.hitl_status ? ` · ${view.hitl_status}` : ""}</h4>
            <div className="mono" style={{ maxHeight: 420, overflow: "auto" }}>{view.tailored_tex || "(not tailored yet — approve the diff)"}</div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Resumes() {
  const [bases, setBases] = useState([]);
  const load = () => api.get("/api/resumes/base").then(setBases).catch(() => setBases([]));
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>Resumes &amp; connections</h1>
      <p className="sub">Upload your base resumes, connect Gmail, and view the tailored version for any job.</p>

      <GmailCard />
      <UploadCard onDone={load} />

      <h3 style={{ fontSize: 15, marginTop: 22 }}>Your base resumes</h3>
      {bases.length === 0
        ? <div className="empty">No base resumes uploaded yet.</div>
        : bases.map((b) => (
          <div key={b.id} className="card" style={{ padding: "10px 16px" }}>
            <div className="row">
              <div>
                <strong className={`tag ${b.track}`}>{b.track}</strong>{" "}
                <span className="muted small">{b.label} · {b.filename || "—"}</span>
                <span className="small muted"> · {b.has_tex ? ".tex" : ""}{b.has_tex && b.has_pdf ? " + " : ""}{b.has_pdf ? ".pdf" : ""}</span>
              </div>
              {b.active ? <span className="tag st-offer">active</span> : <span className="tag">old</span>}
            </div>
          </div>
        ))}

      <h3 style={{ fontSize: 15, marginTop: 22 }}>Tailored resumes</h3>
      <TailoredViewer />
    </>
  );
}
