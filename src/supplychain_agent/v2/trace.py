"""Append-only events plus the input snapshot make completed paths auditable offline."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class TraceStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS v2_runs (
              request_id TEXT PRIMARY KEY, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              request_json TEXT NOT NULL, snapshot_json TEXT, response_json TEXT);
            CREATE TABLE IF NOT EXISTS v2_events (
              request_id TEXT NOT NULL REFERENCES v2_runs(request_id), sequence INTEGER NOT NULL,
              event_json TEXT NOT NULL, PRIMARY KEY(request_id, sequence));
            """)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=2)
        try:
            con.execute("PRAGMA foreign_keys=ON")
            with con:
                yield con
        finally:
            con.close()

    def start(self, request_id, request):
        with self.connect() as con:
            con.execute(
                "INSERT INTO v2_runs(request_id,request_json) VALUES (?,?)",
                (request_id, request.model_dump_json()),
            )

    def snapshot(self, request_id, snapshot):
        with self.connect() as con:
            con.execute(
                "UPDATE v2_runs SET snapshot_json=? WHERE request_id=?",
                (json.dumps(snapshot.to_dict(), ensure_ascii=False), request_id),
            )

    def event(self, request_id, event):
        with self.connect() as con:
            con.execute(
                "INSERT INTO v2_events VALUES (?,?,?)",
                (request_id, event.sequence, event.model_dump_json()),
            )

    def finish(self, response):
        with self.connect() as con:
            con.execute(
                "UPDATE v2_runs SET response_json=? WHERE request_id=?",
                (response.model_dump_json(), response.request_id),
            )

    def get(self, request_id):
        with self.connect() as con:
            row = con.execute(
                "SELECT request_json,snapshot_json,response_json,created_at FROM v2_runs WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if row is None:
                return None
            events = con.execute(
                "SELECT event_json FROM v2_events WHERE request_id=? ORDER BY sequence",
                (request_id,),
            ).fetchall()
        return {
            "request_id": request_id,
            "request": json.loads(row[0]),
            "snapshot": json.loads(row[1]) if row[1] else None,
            "response": json.loads(row[2]) if row[2] else None,
            "created_at": row[3],
            "events": [json.loads(e[0]) for e in events],
        }

    def recent(self, limit=20):
        with self.connect() as con:
            return [
                {"request_id": r[0], "created_at": r[1], "finished": r[2] is not None}
                for r in con.execute(
                    "SELECT request_id,created_at,response_json FROM v2_runs ORDER BY created_at DESC,rowid DESC LIMIT ?",
                    (min(max(limit, 1), 100),),
                )
            ]
