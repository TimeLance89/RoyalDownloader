"""Durable Jellyfin membership and coalesced per-item refresh work."""

import json
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager

DATASETS = {"Movie": "movies", "Series": "series", "Episode": "episodes"}
EVENT_BATCH = 100
MAX_PENDING = 10_000


def item_key(value):
    return str(value or "").replace("-", "").lower()


class JellyfinIndex:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Reserve with private permissions before passing the file to SQLite.
        path.touch(mode=0o600, exist_ok=True)
        with self.connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    scope TEXT PRIMARY KEY, checked_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS items (
                    scope TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
                    series_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY (scope, kind, id)
                );
                CREATE INDEX IF NOT EXISTS items_by_series ON items(scope, kind, series_id);
                CREATE TABLE IF NOT EXISTS pending (
                    scope TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
                    token TEXT NOT NULL, PRIMARY KEY (scope, kind, id)
                );
            """)

    @contextmanager
    def connection(self):
        with closing(sqlite3.connect(self.path, timeout=5)) as db, db:
            yield db

    def last_full(self, scope):
        with self.connection() as db:
            row = db.execute("SELECT checked_at FROM snapshots WHERE scope=?", (scope,)).fetchone()
            return row[0] if row else None

    def read(self, scope, kind, series_ids=None):
        sql = "SELECT payload FROM items WHERE scope=? AND kind=?"
        args = (scope, kind)
        if series_ids is not None:
            sql += " AND series_id IN (SELECT value FROM json_each(?))"
            args += (json.dumps(sorted(series_ids)),)
        with self.connection() as db:
            return [json.loads(payload) for (payload,) in db.execute(sql, args)]

    @staticmethod
    def _write(db, scope, kind, items):
        db.executemany(
            "INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?, ?)",
            ((scope, kind, item_key(row["id"]), row.get("series_id") or "", json.dumps(row))
             for row in items),
        )

    def replace(self, scope, datasets, *, acknowledge=()):
        if datasets.keys() != set(DATASETS.values()) or any(items is None for items in datasets.values()):
            return False
        with self.connection() as db:
            db.execute("DELETE FROM items WHERE scope=?", (scope,))
            for kind, items in datasets.items():
                self._write(db, scope, kind, items)
            db.execute("INSERT OR REPLACE INTO snapshots VALUES (?, ?)", (scope, time.time()))
            db.executemany(
                "DELETE FROM pending WHERE scope=? AND kind=? AND id=? AND token=?",
                ((scope, kind, item_id, token) for kind, item_id, token in acknowledge),
            )
        return True

    def enqueue(self, scope, kind, item_id):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            exists = db.execute(
                "SELECT 1 FROM pending WHERE scope=? AND kind=? AND id=?", (scope, kind, item_id),
            ).fetchone()
            if not exists and db.execute(
                "SELECT count(*) FROM pending WHERE scope=?", (scope,),
            ).fetchone()[0] >= MAX_PENDING:
                return False
            db.execute(
                "INSERT OR REPLACE INTO pending VALUES (?, ?, ?, ?)",
                (scope, kind, item_id, uuid.uuid4().hex),
            )
        return True

    def pending(self, scope, *, limit=EVENT_BATCH):
        with self.connection() as db:
            return db.execute(
                "SELECT kind, id, token FROM pending WHERE scope=? ORDER BY rowid LIMIT ?",
                (scope, limit),
            ).fetchall()

    def apply(self, scope, kind, batch, items):
        received = {item_key(row["id"]): row for row in items}
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            changes = []
            for item_id, token in batch.items():
                if not db.execute(
                    "DELETE FROM pending WHERE scope=? AND kind=? AND id=? AND token=?",
                    (scope, kind, item_id, token),
                ).rowcount:
                    continue
                if item_id in received:
                    changes.append(received[item_id])
                else:
                    db.execute("DELETE FROM items WHERE scope=? AND kind=? AND id=?", (scope, kind, item_id))
            self._write(db, scope, kind, changes)
