from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Project root is one level above /app
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "storyteller.db"

DEFAULT_STATE = {
    "location": "starting_area",
    "inventory": [],
    "flags": {},
    "relationships": {},
}


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r["name"] for r in rows}


def init_db() -> None:
    """
    Create table if missing, and add any missing columns (migration-safe).
    This allows you to upgrade without deleting your existing storyteller.db.
    """
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                history_json TEXT NOT NULL,
                story_text   TEXT NOT NULL,
                state_json   TEXT NOT NULL,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )

        cols = _columns(conn, "sessions")

        # Handle upgrades from older DBs (ALTER TABLE only adds columns)
        if "story_text" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN story_text TEXT NOT NULL DEFAULT ''")
        if "state_json" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}'")

        if "created_at" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
        if "updated_at" not in cols:
            conn.execute("ALTER TABLE sessions ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

        # Backfill state_json for any existing rows that might have '{}' or NULL-ish values
        conn.execute(
            "UPDATE sessions SET state_json = ? WHERE state_json IS NULL OR state_json = '' OR state_json = '{}'",
            (json.dumps(DEFAULT_STATE, ensure_ascii=False),),
        )

        conn.commit()


def migrate_add_state_column() -> None:
    """
    Backwards compatibility: earlier instructions referenced this name.
    """
    init_db()


def save_session(session_id: str, history: list[dict[str, Any]], story_text: str, state: dict[str, Any]) -> None:
    init_db()
    now = datetime.utcnow().isoformat()

    history_json = json.dumps(history, ensure_ascii=False)
    state_json = json.dumps(state, ensure_ascii=False)

    with get_conn() as conn:
        existing = conn.execute(
            "SELECT created_at FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        created_at = existing["created_at"] if existing and existing["created_at"] else now

        conn.execute(
            """
            INSERT INTO sessions (session_id, history_json, story_text, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                history_json = excluded.history_json,
                story_text   = excluded.story_text,
                state_json   = excluded.state_json,
                updated_at   = excluded.updated_at
            """,
            (session_id, history_json, story_text, state_json, created_at, now),
        )
        conn.commit()


def load_session(session_id: str) -> Optional[dict[str, Any]]:
    init_db()

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    if not row:
        return None

    keys = set(row.keys())

    history = json.loads(row["history_json"]) if "history_json" in keys and row["history_json"] else []
    story_text = row["story_text"] if "story_text" in keys and row["story_text"] else ""

    raw_state = row["state_json"] if "state_json" in keys and row["state_json"] else ""
    try:
        state = json.loads(raw_state) if raw_state else DEFAULT_STATE.copy()
    except json.JSONDecodeError:
        state = DEFAULT_STATE.copy()

    # Ensure required keys exist (future-proof)
    state.setdefault("location", "starting_area")
    state.setdefault("inventory", [])
    state.setdefault("flags", {})
    state.setdefault("relationships", {})

    return {
        "session_id": row["session_id"],
        "history": history,
        "story_text": story_text,
        "state": state,
    }
