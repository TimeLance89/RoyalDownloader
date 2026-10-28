"""Private per-user message tombstones, independent from subscriptions/jobs."""
from contextlib import contextmanager
import os
import sqlite3
import threading


class InboxDismissals:
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=3)
        try:
            if os.name == "posix":
                os.chmod(self.path, 0o600)
            db.execute("CREATE TABLE IF NOT EXISTS dismissed (owner TEXT NOT NULL, key TEXT NOT NULL, PRIMARY KEY(owner,key))")
            with db:
                yield db
        finally:
            db.close()

    def keys(self, owner):
        with self.lock, self.connection() as db:
            return [row[0] for row in db.execute("SELECT key FROM dismissed WHERE owner=?", (owner,))]

    def dismiss(self, owner, keys):
        with self.lock, self.connection() as db:
            existing = {row[0] for row in db.execute("SELECT key FROM dismissed WHERE owner=?", (owner,))}
            if len(existing | set(keys)) > 10000:
                raise ValueError("Zu viele gespeicherte Inbox-Entfernungen.")
            db.executemany("INSERT OR IGNORE INTO dismissed(owner,key) VALUES (?,?)", [(owner, key) for key in keys])

    def delete_for_user(self, owner):
        with self.lock, self.connection() as db:
            return db.execute("DELETE FROM dismissed WHERE owner=?", (owner,)).rowcount
