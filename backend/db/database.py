"""SQLite connection helpers and the agent-run audit log.

Every agent writes an `agent_runs` row via `log_run(...)` so the dashboard's Daily
Reporter can show what ran, whether validation passed, and any error text.
"""
from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from backend import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stable_id(*parts: str) -> str:
    """Deterministic short id from the given parts. Use this instead of the builtin
    hash() for dedup keys — hash() is randomized per process (PYTHONHASHSEED), so the
    same input yields different values across runs and breaks INSERT OR IGNORE dedup."""
    joined = "|".join(str(p) for p in parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(db_path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after initial release — applied to already-existing tables. CREATE TABLE
# IF NOT EXISTS won't add columns to a table that already exists, so ALTER them in here.
_MIGRATIONS = [
    "ALTER TABLE tracked_applications ADD COLUMN hidden INTEGER DEFAULT 0",
    "ALTER TABLE tracked_applications ADD COLUMN manual_status INTEGER DEFAULT 0",
    "ALTER TABLE companies ADD COLUMN careers_url TEXT",
]


def _relax_ats_check(conn: sqlite3.Connection) -> None:
    """Older DBs have a CHECK constraint pinning companies.ats_type to 5 values. We now
    support an open set of ATS platforms, so rebuild the table without the CHECK (SQLite
    can't ALTER a constraint). Ids are preserved so jobs.company_id stays valid."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='companies'").fetchone()
    if not row or "CHECK(ats_type" not in row[0]:
        return
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        CREATE TABLE companies_new (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, ats_type TEXT, ats_slug TEXT,
          api_url TEXT, stack_fit TEXT, location TEXT, priority TEXT, notes TEXT, added_at TEXT
        );
        INSERT INTO companies_new (id,name,ats_type,ats_slug,api_url,stack_fit,location,priority,notes,added_at)
          SELECT id,name,ats_type,ats_slug,api_url,stack_fit,location,priority,notes,added_at FROM companies;
        DROP TABLE companies;
        ALTER TABLE companies_new RENAME TO companies;
        PRAGMA foreign_keys=ON;
        """
    )


def init_db(db_path: Optional[Path] = None) -> None:
    """Create all tables (idempotent) and apply migrations."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_conn(db_path) as conn:
        conn.executescript(schema)
        _relax_ats_check(conn)
        for stmt in _MIGRATIONS:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists — fine


def log_run(
    conn: sqlite3.Connection,
    agent_name: str,
    input_ref: str,
    output_ref: str = "",
    validation_passed: bool = True,
    error_text: str = "",
) -> None:
    conn.execute(
        """INSERT INTO agent_runs
           (agent_name, input_ref, output_ref, validation_passed, error_text, ts)
           VALUES (?,?,?,?,?,?)""",
        (agent_name, input_ref, output_ref, 1 if validation_passed else 0, error_text, now_iso()),
    )


def dict_rows(cur: sqlite3.Cursor) -> list[dict[str, Any]]:
    return [dict(r) for r in cur.fetchall()]
