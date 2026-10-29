"""Durable local jobs, voice profiles and projects, with JSON-only records."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .config import data_directory


class Store:
    def __init__(self, filename=None):
        self.path = Path(filename or data_directory("state") / "studio.sqlite3")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, payload TEXT, created REAL, updated REAL, PRIMARY KEY(kind,id))")
        self.connection.commit()
        self.lock = threading.RLock()

    def put(self, kind, payload, identifier=None):
        identifier = identifier or uuid.uuid4().hex
        now = time.time()
        value = {**payload, "id": identifier}
        with self.lock:
            self.connection.execute(
                "INSERT INTO records VALUES (?,?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
                (kind, identifier, json.dumps(value, ensure_ascii=False), now, now))
            self.connection.commit()
        return value

    def get(self, kind, identifier):
        with self.lock:
            row = self.connection.execute("SELECT payload FROM records WHERE kind=? AND id=?", (kind, identifier)).fetchone()
        if row is None:
            raise KeyError(identifier)
        return json.loads(row[0])

    def update(self, kind, identifier, **changes):
        with self.lock:
            value = {**self.get(kind, identifier), **changes}
            return self.put(kind, value, identifier)

    def list(self, kind, limit=200):
        with self.lock:
            rows = self.connection.execute("SELECT payload FROM records WHERE kind=? ORDER BY created DESC LIMIT ?", (kind, limit)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def list_by_status(self, kind, statuses):
        """Read matching records oldest first, without loading terminal history."""
        statuses = tuple(statuses)
        if not statuses:
            return []
        placeholders = ",".join("?" for _ in statuses)
        with self.lock:
            rows = self.connection.execute(
                "SELECT payload FROM records WHERE kind=? "
                f"AND json_extract(payload, '$.status') IN ({placeholders}) "
                "ORDER BY created ASC, rowid ASC", (kind, *statuses)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, kind, identifier):
        with self.lock:
            self.connection.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, identifier))
            self.connection.commit()

    def close(self):
        with self.lock:
            self.connection.close()
