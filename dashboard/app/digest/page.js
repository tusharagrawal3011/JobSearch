"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function Stat({ n, l, warn }) {
  return <div className="stat"><div className="n" style={warn && n > 0 ? { color: "var(--amber)" } : {}}>{n ?? 0}</div><div className="l">{l}</div></div>;
}

export default function Digest() {
  const [d, setD] = useState(null);
  useEffect(() => { api.get("/api/digest").then(setD).catch(() => setD({})); }, []);
  if (!d) return <p className="muted">Loading…</p>;

  const p = d.pending || {};
  const bySource = d.jobs_by_source || {};
  const appliedBySource = d.applied_by_source || {};
  const SRC = ["ats_api", "naukri_alert", "indeed_alert", "cutshort_alert"];

  return (
    <>
      <h1>Daily digest</h1>
      <p className="sub">End-of-day summary from the Daily Reporter.</p>

      <h3 style={{ fontSize: 15 }}>Pending your action</h3>
      <div className="grid">
        <Stat n={p.resume_diffs} l="Resume diffs to approve" warn />
        <Stat n={p.apply_queue} l="Ready to apply" warn />
        <Stat n={p.unanswered_screening} l="Screening gaps" warn />
        <Stat n={p.unverified_contacts} l="Contacts to confirm" warn />
        <Stat n={p.outreach_drafts} l="Outreach drafts" />
        <Stat n={p.flagged_jobs} l="Flagged jobs" warn />
      </div>

      <h3 style={{ fontSize: 15, marginTop: 26 }}>Discovered by channel</h3>
      <div className="grid">
        {SRC.map((s) => <Stat key={s} n={bySource[s]} l={`discovered · ${s}`} />)}
      </div>

      <h3 style={{ fontSize: 15, marginTop: 26 }}>Applied by channel</h3>
      <div className="grid">
        {SRC.map((s) => <Stat key={s} n={appliedBySource[s]} l={`applied · ${s}`} />)}
      </div>

      <h3 style={{ fontSize: 15, marginTop: 26 }}>Recent applications</h3>
      {(d.applied_companies || []).length === 0
        ? <div className="empty">No applications logged yet.</div>
        : (d.applied_companies || []).map((a, i) => (
          <div key={i} className="card" style={{ padding: "10px 16px" }}>
            <div className="row">
              <div><strong>{a.company}</strong> <span className="muted small">· {a.title}</span></div>
              <div className="small muted">
                {a.base_track && <span className={`tag ${a.base_track}`}>{a.base_track}</span>}{" "}
                <span className="tag src">{a.source}</span> {a.applied_at?.slice(0, 10)}
              </div>
            </div>
          </div>
        ))}
    </>
  );
}
