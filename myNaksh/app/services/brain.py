import json
import sqlite3

from app.services.profile import utc_now

KIND_RELATION = {
    "goal": "HAS_GOAL",
    "preference": "PREFERS",
    "interest": "INTERESTED_IN",
    "memory": "HAS_MEMORY",
    "life_area": "HAS_LIFE_AREA",
    "astrology": "HAS_ZODIAC",
}


class BrainService:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def remember_sign(self, user_id: str, sign: str) -> dict:
        return self.remember(
            user_id,
            {
                "kind": "astrology",
                "relation": "HAS_ZODIAC",
                "label": sign,
                "attributes": {},
                "action": "replace",
                "confidence": 1.0,
            },
        )

    def remember(self, user_id: str, fact: dict) -> dict:
        kind = fact["kind"]
        label = fact["label"].strip()
        relation = fact.get("relation") or KIND_RELATION[kind]
        attributes = fact.get("attributes") or {}
        confidence = float(fact.get("confidence") or 0.8)
        action = fact.get("action") or "add"
        replaces = fact.get("replaces")

        if action == "replace":
            if replaces:
                self._supersede_label(user_id, kind, replaces)
            else:
                self._supersede_relation(user_id, relation, keep_label=label)

        existing = self._find_active(user_id, kind, label)
        if existing:
            merged = {**existing["attributes"], **attributes}
            self.conn.execute(
                """
                UPDATE brain_nodes
                SET attributes = ?, confidence = ?, updated_at = ?
                WHERE id = ?
                """,
                (json.dumps(merged), confidence, utc_now(), existing["id"]),
            )
            return self._node_with_relation(existing["id"])

        return self._insert(user_id, kind, label, relation, attributes, confidence)

    def active_memories(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT n.id, n.user_id, n.kind, n.label, n.attributes, n.status,
                   n.confidence, e.relation
            FROM brain_nodes n
            JOIN brain_edges e ON e.to_node_id = n.id
            WHERE n.user_id = ? AND n.status = 'active'
            ORDER BY n.updated_at DESC, n.id DESC
            """,
            (user_id,),
        ).fetchall()
        return [_memory(row) for row in rows]

    def _insert(self, user_id, kind, label, relation, attributes, confidence) -> dict:
        now = utc_now()
        cursor = self.conn.execute(
            """
            INSERT INTO brain_nodes (
                user_id, kind, label, attributes, status, confidence, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
            """,
            (user_id, kind, label, json.dumps(attributes), confidence, now, now),
        )
        node_id = cursor.lastrowid
        self.conn.execute(
            """
            INSERT INTO brain_edges (user_id, from_node_id, relation, to_node_id, created_at)
            VALUES (?, NULL, ?, ?, ?)
            """,
            (user_id, relation, node_id, now),
        )
        return self._node_with_relation(node_id)

    def _find_active(self, user_id: str, kind: str, label: str) -> dict | None:
        row = self.conn.execute(
            """
            SELECT * FROM brain_nodes
            WHERE user_id = ? AND kind = ? AND lower(label) = lower(?) AND status = 'active'
            """,
            (user_id, kind, label),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["attributes"] = json.loads(data["attributes"])
        return data

    def _supersede_label(self, user_id: str, kind: str, label: str) -> None:
        self.conn.execute(
            """
            UPDATE brain_nodes
            SET status = 'superseded', updated_at = ?
            WHERE user_id = ? AND kind = ? AND lower(label) = lower(?) AND status = 'active'
            """,
            (utc_now(), user_id, kind, label),
        )

    def _supersede_relation(self, user_id: str, relation: str, keep_label: str) -> None:
        self.conn.execute(
            """
            UPDATE brain_nodes
            SET status = 'superseded', updated_at = ?
            WHERE id IN (
                SELECT n.id FROM brain_nodes n
                JOIN brain_edges e ON e.to_node_id = n.id
                WHERE n.user_id = ? AND e.relation = ? AND n.status = 'active'
                  AND lower(n.label) != lower(?)
            )
            """,
            (utc_now(), user_id, relation, keep_label),
        )

    def _node_with_relation(self, node_id: int) -> dict:
        row = self.conn.execute(
            """
            SELECT n.id, n.user_id, n.kind, n.label, n.attributes, n.status,
                   n.confidence, e.relation
            FROM brain_nodes n
            JOIN brain_edges e ON e.to_node_id = n.id
            WHERE n.id = ?
            """,
            (node_id,),
        ).fetchone()
        return _memory(row)


def _memory(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["attributes"] = json.loads(data["attributes"])
    return data
