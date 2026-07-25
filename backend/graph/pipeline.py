"""LangGraph StateGraph for a single job's discovery->classify->tailor flow.

Demonstrates the HITL pattern required by the spec: the resume-diff node calls
LangGraph's interrupt() and the run pauses there until the human resumes with an
approve/edit/reject decision. State is persisted via the SQLite checkpointer, so an
interrupted run survives process restarts (Tushar can approve days later).

In practice most work runs in batch (see run_pipeline.py) with the dashboard driving the
HITL steps; this graph is the canonical per-job StateGraph the spec asks for and is used
by `run_pipeline.py --graph <job_id>`.
"""
from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from backend import config
from backend.agents import jd_analyzer, resume_tailor
from backend.db.database import get_conn


class JobState(TypedDict, total=False):
    job_id: int
    stack_guess: str
    resume_id: int
    hitl_decision: dict  # {"action": "approve"|"edit"|"reject", "edited_diff": {...}}
    status: str
    note: str


def _analyze_node(state: JobState) -> JobState:
    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (state["job_id"],)).fetchone()
        res = jd_analyzer.analyze_one(conn, dict(job))
    return {**state, "stack_guess": res.get("stack_guess", ""), "status": res["status"]}


def _tailor_node(state: JobState) -> JobState:
    if state.get("status") == "flagged":
        return {**state, "note": "flagged in analysis; no resume proposed"}
    with get_conn() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (state["job_id"],)).fetchone()
        res = resume_tailor.propose(conn, dict(job))
    if res["status"] == "skipped":
        return {**state, "status": "skipped", "note": "stack=other"}
    return {**state, "resume_id": res["resume_id"], "status": "pending_review"}


def _hitl_node(state: JobState) -> JobState:
    """HITL checkpoint: pause for the human's resume-diff decision."""
    if state.get("status") != "pending_review":
        return state
    decision = interrupt({
        "type": "resume_diff_approval",
        "job_id": state["job_id"],
        "resume_id": state["resume_id"],
        "message": "Approve / edit / reject the tailored resume diff in the dashboard.",
    })
    return {**state, "hitl_decision": decision}


def _finalize_node(state: JobState) -> JobState:
    decision = state.get("hitl_decision") or {}
    action = decision.get("action", "approve")
    if action == "reject":
        resume_tailor.reject(state["resume_id"])
        return {**state, "status": "rejected"}
    result = resume_tailor.finalize(state["resume_id"], decision.get("edited_diff"))
    return {**state, "status": "ready_to_apply", "note": result.get("render", {}).get("note", "")}


def _route_after_tailor(state: JobState) -> str:
    return "hitl" if state.get("status") == "pending_review" else END


def build_graph(checkpointer=None):
    g = StateGraph(JobState)
    g.add_node("analyze", _analyze_node)
    g.add_node("tailor", _tailor_node)
    g.add_node("hitl", _hitl_node)
    g.add_node("finalize", _finalize_node)
    g.add_edge(START, "analyze")
    g.add_edge("analyze", "tailor")
    g.add_conditional_edges("tailor", _route_after_tailor, {"hitl": "hitl", END: END})
    g.add_edge("hitl", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


def run_job_graph(job_id: int, resume_decision: Optional[dict] = None) -> dict:
    """Run (or resume) the per-job graph. First call runs up to the HITL interrupt;
    call again with resume_decision to finalize."""
    from langgraph.types import Command

    with SqliteSaver.from_conn_string(str(config.CHECKPOINT_DB_PATH)) as saver:
        graph = build_graph(saver)
        cfg = {"configurable": {"thread_id": f"job-{job_id}"}}
        if resume_decision is not None:
            result = graph.invoke(Command(resume=resume_decision), cfg)
        else:
            result = graph.invoke({"job_id": job_id}, cfg)
        interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
        return {"job_id": job_id, "state": {k: v for k, v in result.items() if k != "__interrupt__"},
                "interrupted": bool(interrupts)}
