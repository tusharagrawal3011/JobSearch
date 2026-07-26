"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

// Order + labels for the profile form. `full` fields span the whole row.
const FIELDS = [
  { key: "name", label: "Full name", ph: "Ada Lovelace" },
  { key: "email", label: "Email", ph: "you@example.com" },
  { key: "first_name", label: "First name", ph: "Ada" },
  { key: "last_name", label: "Last name", ph: "Lovelace" },
  { key: "phone", label: "Phone", ph: "+1 555 0100" },
  { key: "location", label: "Location", ph: "Bangalore, India" },
  { key: "linkedin", label: "LinkedIn URL", ph: "https://linkedin.com/in/…" },
  { key: "github", label: "GitHub URL", ph: "https://github.com/…" },
  { key: "profile_summary", label: "Profile summary", ph: "Backend engineer (Go/Node), 5 yrs, distributed systems…", full: true, area: true },
  { key: "keyword_filters", label: "Role keywords (comma-separated)", ph: "backend, golang, node, distributed systems", full: true },
  { key: "location_filters", label: "Location filters (comma-separated)", ph: "remote, bangalore, india", full: true },
];

export default function Profile() {
  const [form, setForm] = useState(null);
  const [isSet, setIsSet] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.get("/api/profile").then((d) => {
      setForm(d.profile || {});
      setIsSet(d.is_set);
    }).catch(() => setForm({}));
  }, []);

  function set(k, v) { setForm((f) => ({ ...f, [k]: v })); setSaved(false); }

  async function save() {
    setSaving(true);
    try {
      const r = await api.post("/api/profile", form);
      setForm(r.profile || form);
      setIsSet(true);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) { alert("Error: " + e.message); }
    setSaving(false);
  }

  if (!form) return <p className="muted">Loading…</p>;

  return (
    <>
      <h1>Profile</h1>
      <p className="sub">
        Your identity and search preferences. These fill application forms, ground cover letters,
        outreach and follow-ups, and steer company scouting. Stored locally in your own database —
        overrides the defaults in <span className="mono">.env</span>.
      </p>
      {!isSet && (
        <div className="card stripe st-assessment" style={{ marginBottom: 16 }}>
          <strong>Welcome 👋 Let&apos;s set you up.</strong>
          <div className="small muted" style={{ marginTop: 4 }}>
            Fill in your details below so the agent applies and writes as you. You can edit this anytime.
          </div>
        </div>
      )}
      <div className="grid2">
        {FIELDS.map((f) => (
          <label key={f.key} className={f.full ? "full" : ""}>
            <span className="small muted">{f.label}</span>
            {f.area
              ? <textarea rows={3} value={form[f.key] || ""} placeholder={f.ph} onChange={(e) => set(f.key, e.target.value)} />
              : <input value={form[f.key] || ""} placeholder={f.ph} onChange={(e) => set(f.key, e.target.value)} />}
          </label>
        ))}
      </div>
      <div className="actions" style={{ marginTop: 16 }}>
        <button onClick={save} disabled={saving}>{saving ? "Saving…" : "Save profile"}</button>
        {saved && <span className="small" style={{ color: "var(--ok, #16a34a)" }}>Saved ✓</span>}
      </div>
      <style jsx>{`
        .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; }
        .grid2 label { display: flex; flex-direction: column; gap: 4px; }
        .grid2 label.full { grid-column: 1 / -1; }
        .grid2 input, .grid2 textarea {
          padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px;
          background: var(--card, #fff); color: inherit; font: inherit; width: 100%;
        }
        .grid2 textarea { resize: vertical; }
        @media (max-width: 640px) { .grid2 { grid-template-columns: 1fr; } }
      `}</style>
    </>
  );
}
