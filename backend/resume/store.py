"""Resume library — the user's base resumes stored in the DB.

A user uploads their base resume(s) from the dashboard instead of dropping files on disk.
The active resume per track is what the Resume Tailor works from, and both the original
(base) and the tailored version are viewable per job.

Precedence for loading a base resume: DB (uploaded) first, then the RESUME_*_TEX/PDF files
from .env (the file-based fallback for people who prefer that).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend import config
from backend.db.database import get_conn, now_iso


def save_base_resume(track: str, tex_content: Optional[str], pdf_bytes: Optional[bytes],
                     filename: str = "", label: str = "") -> dict:
    """Store an uploaded base resume and make it the active one for its track."""
    config.ensure_dirs()
    pdf_path = None
    if pdf_bytes:
        safe = f"base_{track}_{int(_ts())}.pdf"
        p = config.RESUME_UPLOAD_DIR / safe
        p.write_bytes(pdf_bytes)
        pdf_path = str(p)
    with get_conn() as conn:
        conn.execute("UPDATE base_resumes SET active=0 WHERE track=?", (track,))
        cur = conn.execute(
            """INSERT INTO base_resumes (track, label, tex_content, pdf_path, filename, active, uploaded_at)
               VALUES (?,?,?,?,?,1,?)""",
            (track, label or track, tex_content, pdf_path, filename, now_iso()),
        )
        rid = cur.lastrowid
    return {"ok": True, "id": rid, "track": track,
            "has_tex": bool(tex_content), "has_pdf": bool(pdf_path)}


def _active(conn, track: str):
    return conn.execute(
        "SELECT * FROM base_resumes WHERE track=? AND active=1 ORDER BY id DESC LIMIT 1",
        (track,)).fetchone()


def get_base_tex(track: str) -> Optional[str]:
    with get_conn() as conn:
        row = _active(conn, track)
    return row["tex_content"] if row and row["tex_content"] else None


def get_base_pdf_path(track: str) -> Optional[str]:
    with get_conn() as conn:
        row = _active(conn, track)
    if row and row["pdf_path"] and Path(row["pdf_path"]).exists():
        return row["pdf_path"]
    return None


def list_base_resumes() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, track, label, filename, active, uploaded_at,
                      (tex_content IS NOT NULL AND tex_content!='') AS has_tex,
                      (pdf_path IS NOT NULL) AS has_pdf
               FROM base_resumes ORDER BY track, active DESC, id DESC""").fetchall()
    return [dict(r) for r in rows]


def _ts() -> float:
    import time
    return time.time()
