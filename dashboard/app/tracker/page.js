"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const STATUS_LABEL = {
  applied: "Applied", assessment: "Assessment", interview: "Interview",
  offer: "Offer", rejected: "Closed", withdrawn: "Closed",
};

function Timeline({ id, reloadKey }) {
  const [events, setEvents] = useState(null);
  useEffect(() => { api.get(`/api/tracker/${id}`).then((d) => setEvents(d.events || [])).catch(() => setEvents([])); }, [id, reloadKey]);
  if (events === null) return <div className="timeline"><span className="small muted">Loading history…</span></div>;
  if (events.length === 0) return null;
  return (
    <div className="timeline">
      {events.map((e) => (
        <div key={e.id} className="tl-item">
          <span className="tl-date">{(e.ts || "").slice(0, 10)}</span>
          {e.status ? <span className={`tag st-${e.status}`} style={{ marginRight: 8 }}>{STATUS_LABEL[e.status] || e.status}</span> : null}
          {e.manual ? <span className="tag" style={{ marginRight: 8, background: "#2a2740", color: "#a78bfa" }}>manual</span> : null}
          {e.manual ? (e.snippet || e.subject) : e.subject}
        </div>
      ))}
    </div>
  );
}

const STATUS_OPTIONS = ["applied", "assessment", "interview", "offer", "rejected", "withdrawn"];

function LogUpdate({ app, onLogged }) {
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!note.trim() && !status) { alert("Add a note or pick a new status."); return; }
    setBusy(true);
    try {
      const r = await api.post(`/api/tracker/${app.id}/event`, { note, status: status || null, on_date: date });
      if (r.error) { alert(r.error); } else { setNote(""); setStatus(""); onLogged(); }
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="logbox">
      <div className="small muted" style={{ marginBottom: 6 }}>Log something that wasn&apos;t in your email — a call, a LinkedIn message, a recruiter chat.</div>
      <textarea rows={2} value={note} placeholder="e.g. HR called — technical interview scheduled for next Tuesday"
                onChange={(e) => setNote(e.target.value)} />
      <div className="logrow">
        <select className="ghost" value={status} onChange={(e) => setStatus(e.target.value)} title="Change status (optional)">
          <option value="">Keep status ({STATUS_LABEL[app.status] || app.status})</option>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>Set: {STATUS_LABEL[s] || s}</option>)}
        </select>
        <input type="date" className="ghost" value={date} onChange={(e) => setDate(e.target.value)} title="When did this happen" />
        <button disabled={busy} onClick={submit}>{busy ? "Saving…" : "Log update"}</button>
      </div>
    </div>
  );
}

function AppCard({ app, onChange }) {
  const [open, setOpen] = useState(false);
  const [logging, setLogging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tlKey, setTlKey] = useState(0);
  const isManual = app.source_domain === "manual";

  async function update(patch) {
    setBusy(true);
    try { await api.post(`/api/tracker/${app.id}/update`, patch); onChange(); }
    catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  function afterLog() { setTlKey((k) => k + 1); setOpen(true); onChange(); }

  return (
    <div className={`card stripe st-${app.status}`}>
      <div className="row">
        <div>
          <strong>{app.role || app.latest_subject}</strong>
          <div className="small muted" style={{ marginTop: 2 }}>
            {app.company}{app.platform === "agency" ? " · via agency" : ""}
            {isManual ? " · added by hand" : (app.manual_status ? " · edited" : "")}
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
          {open ? "Hide history" : "Show history"}
        </button>
        <button className="ghost" style={{ fontSize: 12, padding: "4px 10px" }}
                onClick={() => setLogging(!logging)} title="Log a call / message / update">
          {logging ? "Cancel" : "＋ Log update"}
        </button>
        <select className="ghost" style={{ width: "auto", fontSize: 12, padding: "4px 8px" }}
                disabled={busy} value={app.status}
                onChange={(e) => update({ status: e.target.value })} title="Override status">
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
        </select>
        <button className="ghost" style={{ fontSize: 12, padding: "4px 10px" }}
                disabled={busy} onClick={() => update({ hidden: true })} title="Hide this entry">Hide</button>
      </div>
      {logging && <LogUpdate app={app} onLogged={() => { setLogging(false); afterLog(); }} />}
      {open && <Timeline id={app.id} reloadKey={tlKey} />}
    </div>
  );
}

function AddAppForm({ onAdded, onClose }) {
  const [f, setF] = useState({ company: "", role: "", platform: "direct", status: "applied", applied_on: new Date().toISOString().slice(0, 10), note: "" });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setF((x) => ({ ...x, [k]: v }));

  async function submit() {
    if (!f.company.trim()) { alert("Company is required."); return; }
    setBusy(true);
    try {
      const r = await api.post("/api/tracker/manual", f);
      if (r.error) { alert(r.error); }
      else { if (r.merged && r.note) alert(r.note); onAdded(); onClose(); }
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="card" style={{ borderColor: "var(--accent)" }}>
      <strong>Add an application by hand</strong>
      <div className="small muted" style={{ margin: "2px 0 10px" }}>For roles that never hit your inbox — you applied on a company site, a recruiter reached out on LinkedIn, or an HR called.</div>
      <div className="addgrid">
        <input placeholder="Company *" value={f.company} onChange={(e) => set("company", e.target.value)} />
        <input placeholder="Role" value={f.role} onChange={(e) => set("role", e.target.value)} />
        <select value={f.platform} onChange={(e) => set("platform", e.target.value)}>
          {["direct", "referral", "linkedin", "naukri", "indeed", "agency", "ats", "other"].map((p) => <option key={p} value={p}>{p}</option>)}
        </select>
        <select value={f.status} onChange={(e) => set("status", e.target.value)}>
          {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{STATUS_LABEL[s] || s}</option>)}
        </select>
        <input type="date" value={f.applied_on} onChange={(e) => set("applied_on", e.target.value)} title="When you applied" />
      </div>
      <textarea rows={2} style={{ marginTop: 8 }} placeholder="Optional note (how it came about, contact name…)"
                value={f.note} onChange={(e) => set("note", e.target.value)} />
      <div className="actions" style={{ marginTop: 10 }}>
        <button disabled={busy} onClick={submit}>{busy ? "Adding…" : "Add application"}</button>
        <button className="ghost" onClick={onClose}>Cancel</button>
      </div>
      <style jsx>{`
        .addgrid { display: grid; grid-template-columns: 1.4fr 1.4fr 1fr 1fr 1fr; gap: 8px; }
        .addgrid input, .addgrid select, textarea { padding: 7px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel-2); color: inherit; font: inherit; width: 100%; }
        textarea { resize: vertical; }
        @media (max-width: 760px) { .addgrid { grid-template-columns: 1fr 1fr; } }
      `}</style>
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
  const [adding, setAdding] = useState(false);
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
          <p className="sub">Every role you&apos;ve applied to and its live status — reconstructed from your Gmail, plus anything you log by hand (calls, LinkedIn, referrals).</p>
        </div>
        <div className="actions">
          <button className="ghost" onClick={() => setAdding(!adding)}>{adding ? "Close" : "＋ Add application"}</button>
          <button disabled={busy} onClick={refresh}>{busy ? "Refreshing…" : "↻ Refresh from Gmail"}</button>
        </div>
      </div>

      {adding && <AddAppForm onAdded={load} onClose={() => setAdding(false)} />}

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
        Statuses are inferred from your inbox by keyword rules (no AI, instant). Batch platforms report applications in bulk, so those are counted separately. Education/marketing spam is filtered out. Anything Gmail can&apos;t see, add with <b>＋ Add application</b> or <b>＋ Log update</b>.
      </p>
      <style jsx>{`
        .logbox { margin-top: 10px; padding: 12px; border: 1px dashed var(--border); border-radius: 10px; background: var(--panel-2); }
        .logbox textarea { width: 100%; padding: 7px 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); color: inherit; font: inherit; resize: vertical; }
        .logrow { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; align-items: center; }
        .logrow select, .logrow input { padding: 6px 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--panel); color: inherit; font: inherit; }
        .logrow button { margin-left: auto; }
      `}</style>
    </>
  );
}
