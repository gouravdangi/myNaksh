import sqlite3
import uuid

from app.services.profile import utc_now


class ConversationService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create_session(self, user_id: str) -> dict:
        session_id = str(uuid.uuid4())
        created_at = utc_now()
        self.conn.execute(
            "INSERT INTO sessions (id, user_id, created_at) VALUES (?, ?, ?)",
            (session_id, user_id, created_at),
        )
        return {"id": session_id, "user_id": user_id, "created_at": created_at}

    def get_session(self, session_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def add_message(self, session_id: str, role: str, content: str) -> dict:
        created_at = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO messages (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, created_at),
        )
        return {
            "id": cursor.lastrowid,
            "session_id": session_id,
            "role": role,
            "content": content,
            "created_at": created_at,
        }

    def recent_messages(self, session_id: str, limit: int = 6) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def list_messages(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]
