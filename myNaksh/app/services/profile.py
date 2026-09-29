import sqlite3
import uuid
from datetime import datetime, timezone

from app.astrology import parse_birth_date, sun_sign

PROFILE_FIELDS = (
    "name",
    "date_of_birth",
    "time_of_birth",
    "birth_place",
    "language",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProfileService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, user_id: str | None = None, **fields) -> dict:
        now = utc_now()
        user_id = user_id or str(uuid.uuid4())
        cleaned = _clean_fields(fields)
        self.conn.execute(
            """
            INSERT INTO users (
                id, name, date_of_birth, time_of_birth, birth_place,
                language, sun_sign, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                cleaned.get("name"),
                cleaned.get("date_of_birth"),
                cleaned.get("time_of_birth"),
                cleaned.get("birth_place"),
                cleaned.get("language"),
                sun_sign(cleaned["date_of_birth"]) if cleaned.get("date_of_birth") else None,
                now,
                now,
            ),
        )
        return self.get(user_id)

    def get(self, user_id: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def update(self, user_id: str, **fields) -> dict | None:
        current = self.get(user_id)
        if current is None:
            return None
        cleaned = _clean_fields(fields)
        if not cleaned:
            return current
        for key, value in cleaned.items():
            current[key] = value
        if "date_of_birth" in cleaned:
            current["sun_sign"] = sun_sign(cleaned["date_of_birth"]) if cleaned["date_of_birth"] else None
        current["updated_at"] = utc_now()
        self.conn.execute(
            """
            UPDATE users
            SET name = ?, date_of_birth = ?, time_of_birth = ?, birth_place = ?,
                language = ?, sun_sign = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                current["name"],
                current["date_of_birth"],
                current["time_of_birth"],
                current["birth_place"],
                current["language"],
                current["sun_sign"],
                current["updated_at"],
                user_id,
            ),
        )
        return self.get(user_id)


def _clean_fields(fields: dict) -> dict:
    cleaned = {}
    for key in PROFILE_FIELDS:
        if key not in fields or fields[key] is None:
            continue
        value = str(fields[key]).strip()
        if not value:
            continue
        if key == "date_of_birth":
            parsed = parse_birth_date(value)
            if parsed is None:
                raise ValueError("date_of_birth must be a real date, such as 1995-08-15")
            value = parsed
        cleaned[key] = value
    return cleaned
