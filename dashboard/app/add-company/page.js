"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

export default function AddCompany() {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [companies, setCompanies] = useState([]);
  const [area, setArea] = useState("");
  const [scoutBusy, setScoutBusy] = useState(false);
  const [scoutResult, setScoutResult] = useState(null);

  const load = () => api.get("/api/companies").then(setCompanies).catch(() => setCompanies([]));
  useEffect(() => { load(); }, []);

  async function add() {
    if (!name.trim()) return;
    setBusy(true); setResult(null);
    try {
      const r = await api.post("/api/companies/add", { name: name.trim(), careers_url: url.trim() });
      setResult(r); setName(""); setUrl(""); load();
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  async function scout() {
    if (!area.trim()) return;
    setScoutBusy(true); setScoutResult(null);
    try {
      const r = await api.post("/api/companies/scout", { area: area.trim() });
      setScoutResult(r); load();
    } catch (e) { alert("Error: " + e.message); }
    setScoutBusy(false);
  }

  return (
    <>
      <h1>Add company</h1>
      <p className="sub">Adds the company and runs ATS auto-detection immediately (Greenhouse → Lever → Ashby). If none match, it&apos;s marked <span className="tag">unverified</span> (likely Workday / custom page → semi-auto Playwright flow).</p>

      <div className="card">
        <strong>🔎 Scout an area</strong>
        <p className="small muted" style={{ marginTop: 2 }}>Find companies actively hiring in a location via web search, then auto-add them with ATS detection. Pollable ones (Greenhouse/Lever/Ashby) start feeding Job Discovery immediately.</p>
        <label>Location / area</label>
        <input value={area} onChange={(e) => setArea(e.target.value)} placeholder="e.g. HSR Layout, Bangalore" />
        <div className="actions">
          <button disabled={scoutBusy} onClick={scout}>{scoutBusy ? "Scouting… (web search + ATS detect)" : "Scout & add companies"}</button>
        </div>
        {scoutResult && (
          <div className="checklist" style={{ marginTop: 12 }}>
            Found <strong>{scoutResult.found}</strong>, added <strong>{scoutResult.added}</strong>, {scoutResult.pollable_now} pollable now.
            {(scoutResult.companies || []).map((c, i) => (
              <div key={i} className="small" style={{ marginTop: 4 }}>
                <strong>{c.company}</strong> <span className={`tag ${c.pollable ? "" : "flag"}`}>{c.ats_type || c.status}</span>{" "}
                <span className="muted">{c.roles}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <label>Company name</label>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Hasura" />
        <label>Careers URL (optional)</label>
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/careers" />
        <div className="actions">
          <button disabled={busy} onClick={add}>{busy ? "Detecting ATS…" : "Add & detect ATS"}</button>
        </div>
        {result && (
          <div className="checklist" style={{ marginTop: 12 }}>
            Detected: <strong>{result.name}</strong> → <span className={`tag ${result.ats_type === "unverified" ? "flag" : ""}`}>{result.ats_type}</span>
            {result.ats_slug && <> · slug <code>{result.ats_slug}</code></>}
            {result.api_url && <div className="small mono" style={{ marginTop: 4 }}>{result.api_url}</div>}
          </div>
        )}
      </div>

      <div className="card">
        <strong>One-time setup reminder — job alerts</strong>
        <p className="small muted">Only you can do this, on your own accounts. Do it once per portal so the Email Alert Parser has emails to read:</p>
        <ul className="checklist">
          <li>☐ <strong>Naukri</strong> — create job alerts with your target keywords (Go, Node, backend, SDE) + locations (Bengaluru, Hyderabad, Pune, Remote/India).</li>
          <li>☐ <strong>Indeed</strong> — same keywords/locations; enable email alerts.</li>
          <li>☐ <strong>Cutshort</strong> — same keywords/locations; enable email alerts.</li>
          <li>The portals email matches to your inbox; the parser reads mail sent to you (never contacts their servers).</li>
        </ul>
      </div>

      <h3 style={{ fontSize: 15 }}>Tracked companies ({companies.length})</h3>
      {companies.map((c) => (
        <div key={c.id} className="card" style={{ padding: "10px 16px" }}>
          <div className="row">
            <div><strong>{c.name}</strong> <span className="small muted">· {c.location || "—"} · {c.priority || ""}</span></div>
            <span className={`tag ${c.ats_type === "unverified" ? "flag" : ""}`}>{c.ats_type}{c.ats_slug ? ` · ${c.ats_slug}` : ""}</span>
          </div>
        </div>
      ))}
    </>
  );
}
