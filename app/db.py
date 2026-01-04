from __future__ import annotations

import sqlite3
from pathlib import Path

import json
from datetime import datetime
from typing import Optional

# Project root is one level above /app
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "storyteller.db"


def get_conn() -> sqlite3.Connection:
    """
    Returns a sqlite3 connection with sensible defaults.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    Creates the sessions table if it doesn't exist.
    """
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id   TEXT PRIMARY KEY,
                history_json TEXT NOT NULL,
                story_text   TEXT,
                created_at   TEXT NOT NULL,
                updated_at   TEXT NOT NULL
            )
            """
        )
        conn.commit()


def save_session(session_id: str, history: list, story_text: str | None) -> None:
    now = datetime.utcnow().isoformat()
    payload = json.dumps(history)

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_id, history_json, story_text, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                history_json = excluded.history_json,
                story_text   = excluded.story_text,
                updated_at   = excluded.updated_at
            """,
            (session_id, payload, story_text, now, now),
        )
        conn.commit()


def load_session(session_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "session_id": row["session_id"],
        "history": json.loads(row["history_json"]),
        "story_text": row["story_text"],
    }
