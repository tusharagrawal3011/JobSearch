"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

const pct = (x) => `${Math.round((x || 0) * 100)}%`;

const STAGE_COLOR = {
  Applied: "#9aa3b2", Assessment: "#f4b45f", Interview: "#6ea8ff", Offer: "#58d68a",
};

function Kpi({ label, value, hint }) {
  return (
    <div className="kpi">
      <div className="kpi-val">{value}</div>
      <div className="kpi-label">{label}</div>
      {hint ? <div className="kpi-hint">{hint}</div> : null}
    </div>
  );
}

function Funnel({ funnel }) {
  const top = funnel[0]?.count || 1;
  return (
    <div className="panel">
      <h3>Funnel</h3>
      <p className="small muted" style={{ marginTop: -6 }}>How far your applications actually progressed (rejections counted at the stage they reached).</p>
      {funnel.map((f, i) => {
        const prev = i === 0 ? f.count : funnel[i - 1].count;
        const conv = prev ? Math.round((f.count / prev) * 100) : 0;
        return (
          <div key={f.stage} className="frow">
            <div className="flabel">{f.stage}</div>
            <div className="fbar-wrap">
              <div className="fbar" style={{ width: `${Math.max((f.count / top) * 100, f.count ? 3 : 0)}%`, background: STAGE_COLOR[f.stage] }}>
                <span>{f.count}</span>
              </div>
            </div>
            <div className="fconv small muted">{i === 0 ? "" : `${conv}% of prev`}</div>
          </div>
        );
      })}
    </div>
  );
}

function Months({ months }) {
  if (!months.length) return null;
  const max = Math.max(...months.map((m) => m.applied), 1);
  return (
    <div className="panel">
      <h3>Activity by month</h3>
      <div className="bars">
        {months.map((m) => (
          <div key={m.month} className="bcol" title={`${m.month}: ${m.applied} applied, ${m.interview} interview, ${m.offer} offer`}>
            <div className="bstack">
              <div className="seg applied" style={{ height: `${(m.applied / max) * 120}px` }} />
              {m.interview ? <div className="seg interview" style={{ height: `${(m.interview / max) * 120}px` }} /> : null}
              {m.offer ? <div className="seg offer" style={{ height: `${(m.offer / max) * 120}px` }} /> : null}
            </div>
            <div className="bcount small">{m.applied}</div>
            <div className="blabel small muted">{m.month.slice(2)}</div>
          </div>
        ))}
      </div>
      <div className="legend small muted">
        <span><i className="dot applied" /> Applied</span>
        <span><i className="dot interview" /> Reached interview</span>
        <span><i className="dot offer" /> Offer</span>
      </div>
    </div>
  );
}

function Platforms({ rows }) {
  if (!rows.length) return null;
  return (
    <div className="panel">
      <h3>Which sources convert</h3>
      <table className="ptable">
        <thead>
          <tr><th>Platform</th><th>Apps</th><th>Responded</th><th>Interview</th><th>Offer</th><th style={{ width: "34%" }}>Response rate</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.platform}>
              <td className="cap">{r.platform}</td>
              <td>{r.total}</td>
              <td>{r.responded}</td>
              <td>{r.interview}</td>
              <td>{r.offer}</td>
              <td>
                <div className="rbar-wrap">
                  <div className="rbar" style={{ width: `${(r.response_rate || 0) * 100}%` }} />
                  <span className="small">{pct(r.response_rate)}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Insights() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.get("/api/insights").then(setD).catch((e) => setErr(e.message));
  }, []);

  if (err) return <><h1>Insights</h1><div className="empty">Couldn&apos;t load insights: {err}</div></>;
  if (!d) return <p className="muted">Loading…</p>;

  const t = d.totals, r = d.rates, o = d.outcomes;
  if (!t.tracked) {
    return (
      <>
        <h1>Insights</h1>
        <div className="empty">
          No tracked applications yet. Open <b>My Applications</b> and hit Refresh to reconstruct your
          history from Gmail — then this page shows your funnel, response rates and trends.
        </div>
      </>
    );
  }

  return (
    <>
      <h1>Insights</h1>
      <p className="sub">Your search, measured — reconstructed from {t.tracked} tracked application{t.tracked === 1 ? "" : "s"}
        {t.bulk_volume ? ` (plus ${t.bulk_volume} bulk portal applications not individually tracked)` : ""}. Nothing here is sent anywhere.</p>

      <div className="kpis">
        <Kpi label="Tracked applications" value={t.tracked} hint={`${t.active} in progress`} />
        <Kpi label="Response rate" value={pct(r.response_rate)} hint={`${t.responded} replied`} />
        <Kpi label="Interview rate" value={pct(r.interview_rate)} />
        <Kpi label="Offer rate" value={pct(r.offer_rate)} hint={`${o.offer} offer${o.offer === 1 ? "" : "s"}`} />
        <Kpi label="Median days to reply" value={d.median_days_to_response ?? "—"} hint="first response" />
      </div>

      <div className="grid">
        <Funnel funnel={d.funnel} />
        <div className="panel">
          <h3>Outcomes</h3>
          <ul className="outcomes">
            <li><span className="dot offer" /> Offers <b>{o.offer}</b></li>
            <li><span className="dot interview" /> In progress <b>{o.in_progress}</b></li>
            <li><span className="dot rejected" /> Rejected / closed <b>{o.rejected}</b></li>
            <li><span className="dot none" /> No response yet <b>{o.no_response}</b></li>
          </ul>
        </div>
      </div>

      <Months months={d.by_month} />
      <Platforms rows={d.by_platform} />

      <style jsx>{`
        .kpis { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 18px; }
        .kpi { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
        .kpi-val { font-size: 26px; font-weight: 700; }
        .kpi-label { font-size: 12px; color: var(--muted); margin-top: 2px; }
        .kpi-hint { font-size: 11px; color: var(--muted); margin-top: 4px; opacity: .85; }
        .grid { display: grid; grid-template-columns: 2fr 1fr; gap: 14px; }
        .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; margin-bottom: 14px; }
        .panel h3 { margin: 0 0 12px; font-size: 15px; }
        .frow { display: grid; grid-template-columns: 90px 1fr 90px; align-items: center; gap: 10px; margin: 8px 0; }
        .flabel { font-size: 13px; }
        .fbar-wrap { background: var(--panel-2); border-radius: 6px; overflow: hidden; }
        .fbar { height: 26px; border-radius: 6px; display: flex; align-items: center; justify-content: flex-end; padding-right: 8px; min-width: 24px; transition: width .3s; }
        .fbar span { color: #0e1116; font-weight: 700; font-size: 12px; }
        .fconv { text-align: right; }
        .outcomes { list-style: none; padding: 0; margin: 0; }
        .outcomes li { display: flex; align-items: center; gap: 8px; padding: 7px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
        .outcomes li:last-child { border-bottom: 0; }
        .outcomes b { margin-left: auto; font-size: 15px; }
        .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
        .dot.applied { background: #9aa3b2; } .dot.interview { background: #6ea8ff; }
        .dot.offer { background: #58d68a; } .dot.rejected { background: #ff8098; } .dot.none { background: #4b5563; }
        .bars { display: flex; gap: 10px; align-items: flex-end; overflow-x: auto; padding-bottom: 4px; }
        .bcol { display: flex; flex-direction: column; align-items: center; min-width: 34px; }
        .bstack { display: flex; align-items: flex-end; gap: 2px; height: 130px; }
        .seg { width: 9px; border-radius: 3px 3px 0 0; }
        .seg.applied { background: #3a4451; } .seg.interview { background: #6ea8ff; } .seg.offer { background: #58d68a; }
        .bcount { margin-top: 4px; } .blabel { }
        .legend { display: flex; gap: 16px; margin-top: 10px; }
        .legend span { display: inline-flex; align-items: center; gap: 5px; }
        .legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
        .legend i.applied { background: #3a4451; } .legend i.interview { background: #6ea8ff; } .legend i.offer { background: #58d68a; }
        .ptable { width: 100%; border-collapse: collapse; font-size: 13px; }
        .ptable th { text-align: left; color: var(--muted); font-weight: 500; padding: 6px 8px; border-bottom: 1px solid var(--border); }
        .ptable td { padding: 8px; border-bottom: 1px solid var(--border); }
        .cap { text-transform: capitalize; }
        .rbar-wrap { position: relative; background: var(--panel-2); border-radius: 5px; height: 18px; display: flex; align-items: center; }
        .rbar { position: absolute; left: 0; top: 0; bottom: 0; background: var(--accent); border-radius: 5px; opacity: .55; }
        .rbar-wrap span { position: relative; padding-left: 8px; }
        @media (max-width: 780px) {
          .kpis { grid-template-columns: repeat(2, 1fr); }
          .grid { grid-template-columns: 1fr; }
        }
      `}</style>
    </>
  );
}
