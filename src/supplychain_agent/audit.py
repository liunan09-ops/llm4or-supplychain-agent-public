"""Local SQLite run history. Credentials and provider request headers are never recorded."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .schemas import AgentRequest, AgentResponse


class AuditStore:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute(
                "CREATE TABLE IF NOT EXISTS runs ("
                "request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, "
                "request_json TEXT NOT NULL, response_json TEXT NOT NULL)"
            )

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.path, timeout=10)
        try:
            with con:
                yield con
        finally:
            con.close()

    def save(self, request: AgentRequest, response: AgentResponse):
        with self._connect() as con:
            con.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?)",
                (
                    response.request_id,
                    datetime.now(UTC).isoformat(),
                    request.model_dump_json(),
                    response.model_dump_json(),
                ),
            )

    def get(self, request_id: str) -> dict | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT created_at, request_json, response_json FROM runs WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        return {"created_at": row[0], "request": json.loads(row[1]), "response": json.loads(row[2])}

    def recent(self, limit: int = 20) -> list[dict]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT request_id, created_at, request_json, response_json FROM runs "
                "ORDER BY created_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            {
                "request_id": row[0],
                "created_at": row[1],
                "message": json.loads(row[2])["message"],
                "status": json.loads(row[3])["status"],
                "mode": json.loads(row[3])["mode"],
            }
            for row in rows
        ]
