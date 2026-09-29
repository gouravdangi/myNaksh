import json
import sqlite3

from app.services.llm import LLMResult
from app.services.profile import utc_now


class ObservabilityService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def log_llm_call(
        self,
        *,
        user_id: str,
        session_id: str,
        step: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        latency_ms: int,
        status: str,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO llm_calls (
                user_id, session_id, step, model, prompt_tokens, completion_tokens,
                total_tokens, latency_ms, status, error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                session_id,
                step,
                model,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                latency_ms,
                status,
                error,
                utc_now(),
            ),
        )

    def log_success(self, user_id: str, session_id: str, step: str, result: LLMResult) -> None:
        self.log_llm_call(
            user_id=user_id,
            session_id=session_id,
            step=step,
            model=result.model,
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            total_tokens=result.usage.total_tokens,
            latency_ms=result.latency_ms,
            status="ok",
        )

    def log_request(
        self,
        *,
        user_id: str,
        session_id: str,
        latency_ms: int,
        context_used: list[str],
        status: str,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO request_logs (user_id, session_id, latency_ms, context_used, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, session_id, latency_ms, json.dumps(context_used), status, utc_now()),
        )

    def latest_context(self, session_id: str) -> list[str]:
        row = self.conn.execute(
            """
            SELECT context_used FROM request_logs
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return []
        return json.loads(row["context_used"])

    def list_requests(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM request_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        items = []
        for row in rows:
            data = dict(row)
            data["context_used"] = json.loads(data["context_used"])
            items.append(data)
        return items

    def list_llm_calls(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM llm_calls ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
