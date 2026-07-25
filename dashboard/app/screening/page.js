"use client";
import { useEffect, useState } from "react";
import { api } from "../lib/api";

function GapRow({ gap, onSaved }) {
  const [go, setGo] = useState(gap.answer_go || "");
  const [node, setNode] = useState(gap.answer_node || "");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!go && !node) { alert("Enter at least one answer."); return; }
    setBusy(true);
    try {
      await api.post("/api/screening-gaps/save", {
        question_key: gap.question_key, question_text: gap.question_text,
        answer_go: go, answer_node: node,
      });
      onSaved(gap.question_key);
    } catch (e) { alert("Error: " + e.message); }
    setBusy(false);
  }

  return (
    <div className="card">
      <strong>{gap.question_text}</strong>
      <div className="diff" style={{ marginTop: 8 }}>
        <div>
          <label>Answer — Go track</label>
          <textarea value={go} onChange={(e) => setGo(e.target.value)} placeholder="e.g. 4 years with Go" />
        </div>
        <div>
          <label>Answer — Node track</label>
          <textarea value={node} onChange={(e) => setNode(e.target.value)} placeholder="e.g. 3 years with Node.js" />
        </div>
      </div>
      <div className="actions">
        <button className="green" disabled={busy} onClick={save}>Save answer</button>
        <span className="small muted" style={{ alignSelf: "center" }}>
          Reused automatically for matching questions across all companies.
        </span>
      </div>
    </div>
  );
}

export default function Screening() {
  const [gaps, setGaps] = useState(null);
  const load = () => api.get("/api/screening-gaps").then(setGaps).catch(() => setGaps([]));
  useEffect(() => { load(); }, []);

  return (
    <>
      <h1>Screening Q&A gaps</h1>
      <p className="sub">Questions the Application agent hit that the system has no answer for. It left them blank and flagged them here — nothing is ever guessed. Answer per track.</p>
      {gaps === null ? <p className="muted">Loading…</p>
        : gaps.length === 0 ? <div className="empty">No unanswered screening questions. 🎉</div>
        : gaps.map((g) => <GapRow key={g.question_key} gap={g} onSaved={load} />)}
    </>
  );
}
