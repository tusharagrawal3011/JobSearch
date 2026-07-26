"""User profile — the effective identity + search preferences.

Precedence: the DB `profile` row (edited in the UI) overlays the `.env` defaults from config.
So an existing user's `.env` keeps working, and a fresh user can set everything up in the
dashboard without touching files. Agents call `get()` at runtime so edits take effect live.
"""
from __future__ import annotations

from backend import config
from backend.db.database import get_conn, now_iso

FIELDS = ("name", "first_name", "last_name", "email", "phone", "linkedin", "github",
          "location", "profile_summary", "keyword_filters", "location_filters")


def _env_defaults() -> dict:
    return {
        "name": config.OWNER_NAME, "first_name": config.OWNER_FIRST_NAME,
        "last_name": config.OWNER_LAST_NAME, "email": config.OWNER_EMAIL,
        "phone": config.OWNER_PHONE, "linkedin": config.OWNER_LINKEDIN,
        "github": config.OWNER_GITHUB, "location": config.OWNER_LOCATION,
        "profile_summary": config.OWNER_PROFILE,
        "keyword_filters": ",".join(config.KEYWORD_FILTERS),
        "location_filters": ",".join(config.LOCATION_FILTERS),
    }


def get() -> dict:
    """Effective profile: DB values where set, else the .env defaults."""
    eff = _env_defaults()
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM profile WHERE id=1").fetchone()
    if row:
        for f in FIELDS:
            v = row[f]
            if v is not None and str(v).strip():
                eff[f] = v
    return eff


def is_set() -> bool:
    """True once the user has saved a profile via the UI (so onboarding can prompt)."""
    with get_conn() as conn:
        return conn.execute("SELECT 1 FROM profile WHERE id=1").fetchone() is not None


def save(fields: dict) -> dict:
    cols = [f for f in FIELDS if f in fields]
    with get_conn() as conn:
        existing = conn.execute("SELECT 1 FROM profile WHERE id=1").fetchone()
        if existing:
            sets = ", ".join(f"{c}=?" for c in cols) + ", updated_at=?"
            conn.execute(f"UPDATE profile SET {sets} WHERE id=1",
                         [fields[c] for c in cols] + [now_iso()])
        else:
            conn.execute(
                f"INSERT INTO profile (id, {', '.join(cols)}, updated_at) "
                f"VALUES (1, {', '.join('?' for _ in cols)}, ?)",
                [fields[c] for c in cols] + [now_iso()])
    return {"ok": True, "profile": get()}
