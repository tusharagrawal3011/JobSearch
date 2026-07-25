"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const STATUS_LABEL = {
  applied: "Applied", assessment: "Assessment", interview: "Interview",
  offer: "Offer", rejected: "Closed", withdrawn: "Closed",
};

function Timeline({ id }) {
  const [events, setEvents] = useState(null);
  useEffect(() => { api.get(`/api/tracker/${id}`).then((d) => setEvents(d.events || [])).catch(() => setEvents([])); }, [id]);
  if (events === null) return <div className="timeline"><span className="small muted">Loading history…</span></div>;
  if (events.length === 0) return null;
  return (
    <div className="timeline">
      {events.map((e) => (
        <div key={e.id} className="tl-item">
          <span className="tl-date">{(e.ts || "").slice(0, 10)}</span>
          <span className={`tag st-${e.status}`} style={{ marginRight: 8 }}>{STATUS_LABEL[e.status] || e.status}</span>
          {e.subject}
        </div>
      ))}
    </div>
  );
}

const STATUS_OPTIONS = ["applied", "assessment", "interview", "offer", "rejected", "withdrawn"];

function AppCard({ app, onChange }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  async function update(patch) {
    setBusy(true);
    try { await api.post(`/api/tracker/${app.id}/update`, patch); onChange(); }
    catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className={`card stripe st-${app.status}`}>
      <div className="row">
        <div>
          <strong>{app.role || app.latest_subject}</strong>
          <div className="small muted" style={{ marginTop: 2 }}>
            {app.company}{app.platform === "agency" ? " · via agency" : ""}
            {app.manual_status ? " · edited" : ""}
          </div>
          {app.needs_action ? <div className="pill-warn" style={{ marginTop: 4 }}>⚠ {app.action_hint}</div> : null}
        </div>
        <div className="right" style={{ textAlign: "right" }}>
          <span className={`tag st-${app.status}`}>{STATUS_LABEL[app.status] || app.status}</span>
          <div className="small muted" style={{ marginTop: 4 }}>{(app.last_update || "").slice(0, 10)}</div>
        </div>
      </div>
      <div className="actions" style={{ marginTop: 10 }}>
        <button className="ghost" style={{ fontSize: 12, padding: "4px 10px" }} onClick={() => setOpen(!open)}>
          {open ? "Hide history" : "Show email history"}
        </button>
        <select className="ghost" style={{ width: "auto", fontSize: 12, padding: "4px 8px" }}
                disabled={busy} value={app.status}
                onChange={(e) => update({ status: e.target.value })} title="Override status">
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
        </select>
        <button className="ghost" style={{ fontSize: 12, padding: "4px 10px" }}
                disabled={busy} onClick={() => update({ hidden: true })} title="Hide this entry">Hide</button>
      </div>
      {open && <Timeline id={app.id} />}
    </div>
  );
}

function Stat({ n, l, hero }) {
  return <div className="stat" style={hero ? { background: "var(--accent)", color: "#fff" } : {}}>
    <div className="n" style={hero ? { color: "#fff" } : {}}>{n ?? 0}</div><div className="l" style={hero ? { color: "rgba(255,255,255,.85)" } : {}}>{l}</div>
  </div>;
}

export default function Tracker() {
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.get("/api/tracker").then(setData).catch(() => setData({ applications: [] }));
  useEffect(() => { load(); }, []);

  async function refresh() {
    setBusy(true);
    try { await api.post("/api/tracker/refresh", {}); await load(); }
    catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  if (!data) return <p className="muted">Loading…</p>;
  const apps = data.applications || [];
  const sc = data.status_counts || {};
  const active = apps.filter((a) => a.status === "interview" || a.status === "assessment");
  const applied = apps.filter((a) => a.status === "applied");
  const closed = apps.filter((a) => a.status === "rejected" || a.status === "withdrawn" || a.status === "offer");
  const needs = data.needs_action || [];

  return (
    <>
      <div className="row">
        <div>
          <h1>My Applications</h1>
          <p className="sub">Every role you&apos;ve applied to and its live status — reconstructed from your Gmail (application confirmations, recruiter emails, interviews, assessments, rejections).</p>
        </div>
        <button disabled={busy} onClick={refresh}>{busy ? "Refreshing…" : "↻ Refresh from Gmail"}</button>
      </div>

      {needs.length > 0 && (
        <div className="action-banner">
          <strong>⚠ {needs.length} need your attention:</strong>{" "}
          {needs.map((n, i) => <span key={n.id}>{i > 0 ? " · " : ""}{n.company} ({n.action_hint})</span>)}
        </div>
      )}

      <div className="grid" style={{ marginBottom: 8 }}>
        <Stat n={data.active_processes} l="Active — interviews & assessments" hero />
        <Stat n={apps.length + (data.total_volume_applications || 0)} l="Total applications" />
        <Stat n={sc.interview || 0} l="At interview stage" />
        <Stat n={applied.length} l="Applied · awaiting reply" />
      </div>

      <h3 style={{ fontSize: 15, marginTop: 24 }}>🔥 Active pipeline <span className="muted small">— interviews & assessments</span></h3>
      {active.length === 0 ? <div className="empty">No active processes detected.</div>
        : active.map((a) => <AppCard key={a.id} app={a} onChange={load} />)}

      {closed.length > 0 && <>
        <h3 style={{ fontSize: 15, marginTop: 24 }}>Outcomes</h3>
        {closed.map((a) => <AppCard key={a.id} app={a} onChange={load} />)}
      </>}

      <h3 style={{ fontSize: 15, marginTop: 24 }}>Applied · awaiting response</h3>
      {applied.length === 0 ? <div className="empty">Nothing awaiting.</div>
        : applied.map((a) => <AppCard key={a.id} app={a} onChange={load} />)}

      <h3 style={{ fontSize: 15, marginTop: 24 }}>Volume by platform</h3>
      <div className="grid">
        {Object.entries(data.volume_by_platform || {}).map(([p, n]) =>
          <Stat key={p} n={n} l={`${p} · batch applications`} />)}
        {(!data.volume_by_platform || Object.keys(data.volume_by_platform).length === 0) &&
          <div className="empty" style={{ gridColumn: "1/-1" }}>No batch-application emails found.</div>}
      </div>

      <p className="small muted" style={{ marginTop: 24 }}>
        Statuses are inferred from your inbox by keyword rules (no AI, instant). Batch platforms report applications in bulk, so those are counted separately. Education/marketing spam is filtered out.
      </p>
    </>
  );
}
