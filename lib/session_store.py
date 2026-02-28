"""
session_store.py — SQLite Persistence Layer / SQLite 持久化层

Two tables: / 两张表:
  sessions      — session_id PK, data JSON, status, updated_at
  sent_messages — session_id, message_id
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from typing import Optional

from lib.protocol import AIMPSession, AIMPRoom


class SessionStore:
    def __init__(self, db_path: str = "~/.aimp/sessions.db"):
        """
        Initialize SQLite connection / 初始化 SQLite 连接
        Args:
            db_path: Path to database file / 数据库文件路径
        """
        self.db_path = os.path.expanduser(db_path)
        if self.db_path != ":memory:":
            db_dir = os.path.dirname(self.db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self):
        """Create necessary tables if they don't exist / 如果表不存在则创建"""
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
            CREATE TABLE IF NOT EXISTS rooms (
                room_id    TEXT PRIMARY KEY,
                data       TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'open',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pending_emails (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT,
                room_id       TEXT,
                received_at   REAL NOT NULL,
                from_addr     TEXT NOT NULL,
                subject       TEXT,
                body          TEXT,
                protocol_json TEXT,
                processed     INTEGER NOT NULL DEFAULT 0
            );
        """)
        self._conn.commit()

    # ── Session CRUD / Session 增删改查 ──────────────────────────────────

    def save(self, session: AIMPSession):
        """Save session to database / 保存 session 到数据库"""
        data_json = json.dumps(session.to_json(), ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO sessions (session_id, data, status, updated_at) VALUES (?, ?, ?, ?)",
            (session.session_id, data_json, session.status, time.time()),
        )
        self._conn.commit()

    def load(self, session_id: str) -> Optional[AIMPSession]:
        """Load session from database / 从数据库加载 session"""
        row = self._conn.execute(
            "SELECT data FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        return AIMPSession.from_json(json.loads(row[0]))

    def load_active(self) -> list[AIMPSession]:
        """Load all active (negotiating) sessions / 加载所有活跃的（协商中）会话"""
        rows = self._conn.execute(
            "SELECT data FROM sessions WHERE status = 'negotiating' ORDER BY updated_at DESC"
        ).fetchall()
        return [AIMPSession.from_json(json.loads(r[0])) for r in rows]

    def delete(self, session_id: str):
        """Delete session and its associated message IDs / 删除 session 及其关联的消息 ID"""
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.execute("DELETE FROM sent_messages WHERE session_id = ?", (session_id,))
        self._conn.commit()

    # ── Message ID tracking / 消息 ID 追踪 ──────────────────────────

    def save_message_id(self, session_id: str, message_id: str):
        """Save sent message ID for threading / 保存已发送消息的 ID，用于构建回复链"""
        self._conn.execute(
            "INSERT OR IGNORE INTO sent_messages (session_id, message_id) VALUES (?, ?)",
            (session_id, message_id),
        )
        self._conn.commit()

    def load_message_ids(self, session_id: str) -> list[str]:
        """Load all sent message IDs for a session / 加载会话的所有已发送消息 ID"""
        rows = self._conn.execute(
            "SELECT message_id FROM sent_messages WHERE session_id = ?", (session_id,)
        ).fetchall()
        return [r[0] for r in rows]

    # ── Room CRUD (Phase 2) / Room 增删改查 ──────────────────────────────────

    def save_room(self, room: AIMPRoom):
        """Save AIMPRoom to database / 保存 AIMPRoom 到数据库"""
        data_json = json.dumps(room.to_json(), ensure_ascii=False)
        self._conn.execute(
            "INSERT OR REPLACE INTO rooms (room_id, data, status, updated_at) VALUES (?, ?, ?, ?)",
            (room.room_id, data_json, room.status, time.time()),
        )
        self._conn.commit()

    def load_room(self, room_id: str) -> Optional[AIMPRoom]:
        """Load AIMPRoom from database / 从数据库加载 AIMPRoom"""
        row = self._conn.execute(
            "SELECT data FROM rooms WHERE room_id = ?", (room_id,)
        ).fetchone()
        if not row:
            return None
        return AIMPRoom.from_json(json.loads(row[0]))

    def load_open_rooms(self) -> list[AIMPRoom]:
        """Load all open (non-finalized) rooms / 加载所有未完成的 Room"""
        rows = self._conn.execute(
            "SELECT data FROM rooms WHERE status = 'open' ORDER BY updated_at DESC"
        ).fetchall()
        return [AIMPRoom.from_json(json.loads(r[0])) for r in rows]

    # ── Pending Email Store (Store-First) / 待处理邮件存储 ────────────────────────

    def save_pending_email(self, from_addr: str, subject: str, body: str,
                           protocol_json: str = None, session_id: str = None,
                           room_id: str = None) -> int:
        """Persist an incoming email before processing / 在处理前持久化收到的邮件"""
        cur = self._conn.execute(
            "INSERT INTO pending_emails "
            "(session_id, room_id, received_at, from_addr, subject, body, protocol_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (session_id, room_id, time.time(), from_addr, subject, body, protocol_json),
        )
        self._conn.commit()
        return cur.lastrowid

    def load_pending_for_session(self, session_id: str) -> list[dict]:
        """Load all unprocessed pending emails for a session / 加载 session 的所有未处理邮件"""
        rows = self._conn.execute(
            "SELECT id, from_addr, subject, body, protocol_json FROM pending_emails "
            "WHERE session_id = ? AND processed = 0 ORDER BY received_at",
            (session_id,)
        ).fetchall()
        return [{"id": r[0], "from_addr": r[1], "subject": r[2],
                 "body": r[3], "protocol_json": r[4]} for r in rows]

    def load_pending_for_room(self, room_id: str) -> list[dict]:
        """Load all unprocessed pending emails for a room / 加载 Room 的所有未处理邮件"""
        rows = self._conn.execute(
            "SELECT id, from_addr, subject, body, protocol_json FROM pending_emails "
            "WHERE room_id = ? AND processed = 0 ORDER BY received_at",
            (room_id,)
        ).fetchall()
        return [{"id": r[0], "from_addr": r[1], "subject": r[2],
                 "body": r[3], "protocol_json": r[4]} for r in rows]

    def mark_processed(self, email_id: int):
        """Mark a pending email as processed / 标记邮件为已处理"""
        self._conn.execute(
            "UPDATE pending_emails SET processed = 1 WHERE id = ?", (email_id,)
        )
        self._conn.commit()

    def close(self):
        """Close database connection / 关闭数据库连接"""
        self._conn.close()
