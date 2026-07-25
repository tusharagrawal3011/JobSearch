"""Screening question bank helpers.

The `screening_answers` table ships EMPTY. When the Application agent meets a question
it can't match, it records the question (empty answers) and the job is flagged
'needs your input'. Once the human fills an answer (per track) via the dashboard, it is
reused automatically for future matching questions across all companies.
"""
from __future__ import annotations

import re

from backend.db.database import get_conn, now_iso

_STOP = {"the", "a", "an", "of", "for", "your", "you", "do", "have", "with", "in", "on",
         "to", "is", "are", "what", "how", "many", "please", "this", "role", "and", "or"}


def question_key(text: str) -> str:
    """Normalize a question into a stable fuzzy key (sorted significant tokens)."""
    tokens = [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOP and len(t) > 1]
    return " ".join(sorted(set(tokens)))[:200]


def _overlap(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def match_answer(conn, question_text: str, track: str, threshold: float = 0.6) -> str | None:
    """Return a stored answer for this track if a sufficiently similar question exists."""
    key = question_key(question_text)
    col = "answer_go" if track == "go" else "answer_node"
    rows = conn.execute("SELECT question_key, answer_go, answer_node FROM screening_answers").fetchall()
    best, best_score = None, 0.0
    for r in rows:
        score = 1.0 if r["question_key"] == key else _overlap(key, r["question_key"])
        if score > best_score:
            best, best_score = r, score
    if best and best_score >= threshold:
        ans = best["answer_go"] if track == "go" else best["answer_node"]
        return ans or None
    return None


def record_gap(conn, question_text: str) -> None:
    """Insert an empty row for an unanswered question (idempotent by key)."""
    key = question_key(question_text)
    conn.execute(
        """INSERT OR IGNORE INTO screening_answers (question_key, question_text, last_updated)
           VALUES (?,?,?)""",
        (key, question_text, now_iso()),
    )


def save_answer(question_key_or_text: str, answer_go: str, answer_node: str,
                question_text: str | None = None) -> dict:
    """Dashboard entrypoint: fill/update an answer for a question (per track)."""
    key = question_key(question_text or question_key_or_text)
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO screening_answers (question_key, question_text, answer_go, answer_node, last_updated)
               VALUES (?,?,?,?,?)
               ON CONFLICT(question_key) DO UPDATE SET
                 answer_go=excluded.answer_go,
                 answer_node=excluded.answer_node,
                 question_text=COALESCE(excluded.question_text, screening_answers.question_text),
                 last_updated=excluded.last_updated""",
            (key, question_text or question_key_or_text, answer_go, answer_node, now_iso()),
        )
    return {"ok": True, "question_key": key}


def open_gaps(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM screening_answers
           WHERE (answer_go IS NULL OR answer_go='') AND (answer_node IS NULL OR answer_node='')"""
    ).fetchall()
    return [dict(r) for r in rows]
