"""
session_store.py — SQLite 持久化层，替代内存 dict

两张表:
  sessions      — session_id PK, data JSON, status, updated_at
  sent_messages — session_id, message_id
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from typing import Optional

from lib.protocol import AIMPSession


class SessionStore:
    def __init__(self, db_path: str = "~/.aimp/sessions.db"):
        self.db_path = os.path.expanduser(db_path)
        if self.db_path != ":memory:":
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'negotiating',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sent_messages (
                session_id TEXT NOT NULL,
                message_id TEXT NOT NULL,
                PRIMARY KEY (session_id, message_id)
            );
        """)
        self._conn.commit()

    # ── Session CRUD ──────────────────────────────────

    def save(self, session: AIMPSession):
        data_json = json.dumps(session.to_json(), ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, data, status, updated_at) VALUES (?, ?, ?, ?)",
            (session.session_id, data_json, session.status, time.time()),
        )
        self._conn.commit()

    def load(self, session_id: str) -> Optional[AIMPSession]:
        row = self._conn.execute(
            "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return AIMPSession.from_json(json.loads(row[0]))

    def load_active(self) -> list[AIMPSession]:
        rows = self._conn.execute(
            "SELECT data FROM sessions WHERE status = 'negotiating' ORDER BY updated_at DESC"
        ).fetchall()
        return [AIMPSession.from_json(json.loads(r[0])) for r in rows]

    def delete(self, session_id: str):
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sent_messages WHERE session_id = ?", (session_id,))
        self._conn.commit()

    # ── Message ID tracking ──────────────────────────

    def save_message_id(self, session_id: str, message_id: str):
        self._conn.execute(
            "INSERT OR IGNORE INTO sent_messages (session_id, message_id) VALUES (?, ?)",
            (session_id, message_id),
        )
        self._conn.commit()

    def load_message_ids(self, session_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT message_id FROM sent_messages WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [r[0] for r in rows]

    def close(self):
        self._conn.close()
