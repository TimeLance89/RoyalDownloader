"""Durable, cross-process serialization of completed-media scan requests.

No network or ffprobe work runs in download completion callbacks. SQLite stores
only media paths/stat identities and safe state codes, never server credentials.
"""
from contextlib import contextmanager
import hashlib
import logging
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

logger = logging.getLogger(__name__)


def interval(name, default, minimum):
    try:
        return max(minimum, min(int(os.environ.get(name, default)), 86400))
    except (ValueError, TypeError):
        return default


def file_identity(path):
    path = Path(path).absolute()
    if any(part.casefold() == ".downloading" for part in path.parts) or path.suffix.lower() not in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v", ".ts"}:
        raise ValueError("unfinished_or_unsupported")
    if any(parent.is_symlink() for parent in (path, *path.parents)) or not path.is_file():
        raise ValueError("missing_final_file")
    info = path.stat()
    return str(path), f"{info.st_dev}:{info.st_ino}:{info.st_size}:{info.st_mtime_ns}"


@contextmanager
def dispatch_lock(path):
    """Kernel-owned lock survives threads and is released on process death."""
    with open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, 2)
            if not handle.tell():
                handle.write(b"0"); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
            try:
                yield True
            finally:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class ScanManager:
    def __init__(self, path, get_client, *, on_submitted=lambda: None,
                 validate=None, recognized=lambda evidence: None, clock=time.time, debounce=60, cooldown=300,
                 retry_base=300, max_attempts=3, max_age=86400):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.get_client = get_client
        self.on_submitted = on_submitted
        self.validate = validate or self._validate
        self.recognized = recognized
        self.clock = clock
        self.debounce = debounce
        self.cooldown = cooldown
        self.retry_base = retry_base
        self.max_attempts = max_attempts
        self.max_age = max_age
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.guard = threading.Lock()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS media (
                    server TEXT, identity TEXT, path TEXT, signature TEXT,
                    source TEXT, created REAL, due REAL, attempts INTEGER DEFAULT 0,
                    state TEXT DEFAULT 'pending', reason TEXT DEFAULT '',
                    evidence TEXT DEFAULT '{}', submitted_at REAL DEFAULT 0,
                    PRIMARY KEY(server, identity));
                CREATE TABLE IF NOT EXISTS scans (
                    server TEXT PRIMARY KEY, last_start REAL DEFAULT 0, last_attempt REAL DEFAULT 0,
                    phase TEXT DEFAULT 'idle', submitted INTEGER DEFAULT 0,
                    avoided INTEGER DEFAULT 0, requests INTEGER DEFAULT 0);
                CREATE INDEX IF NOT EXISTS media_due ON media(server,state,due);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(media)")}
            for name, kind in (("evidence", "TEXT DEFAULT '{}'"), ("submitted_at", "REAL DEFAULT 0")):
                if name not in columns:
                    db.execute(f"ALTER TABLE media ADD COLUMN {name} {kind}")
            if "last_attempt" not in {row[1] for row in db.execute("PRAGMA table_info(scans)")}:
                db.execute("ALTER TABLE scans ADD COLUMN last_attempt REAL DEFAULT 0")

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _validate(path):
        from media.downloader import validate_media_file
        return validate_media_file(Path(path))[0]

    def target(self):
        client = self.get_client()
        if not client.configured:
            return client, ""
        # Scope by server/provider, not API key: key rotation retains pending work.
        raw = f"{type(client).__name__}:{client.base_url}"
        return client, hashlib.sha256(raw.encode()).hexdigest()

    def request(self, source, path, evidence=None):
        client, server = self.target()
        if not server:
            return "unconfigured"
        try:
            path, signature = file_identity(path)
        except (ValueError, OSError):
            logger.warning("Media scan request rejected source=%s reason=invalid_final_file", source)
            return "invalid_final_file"
        identity = hashlib.sha256(f"{path}:{signature}".encode()).hexdigest()
        now = self.clock()
        evidence = {key: value for key, value in (evidence or {}).items() if key in {"kind", "title", "year", "tmdb_id", "season", "episode"}}
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO scans(server) VALUES (?)", (server,))
            inserted = db.execute("INSERT OR IGNORE INTO media(server,identity,path,signature,source,created,due) VALUES(?,?,?,?,?,?,?)",
                                  (server, identity, path, signature, source, now, now + self.debounce)).rowcount
            if evidence:
                db.execute("UPDATE media SET evidence=? WHERE server=? AND identity=? AND evidence='{}'", (json.dumps(evidence), server, identity))
            db.execute("UPDATE scans SET requests=requests+1,avoided=avoided+? WHERE server=?", (int(not inserted), server))
        logger.info("Media scan request source=%s state=%s", source, "queued" if inserted else "deduplicated")
        self.wake.set()
        return "queued" if inserted else "deduplicated"

    def _state(self, server, phase):
        with self.db() as db:
            db.execute("UPDATE scans SET phase=? WHERE server=?", (phase, server))

    def _failed(self, server, rows, reason):
        now = self.clock()
        with self.db() as db:
            for row in rows:
                attempts = row["attempts"] + 1
                state = "failed" if attempts >= self.max_attempts else "pending"
                db.execute("UPDATE media SET state=?,attempts=?,reason=?,due=? WHERE server=? AND identity=?",
                           (state, attempts, reason, now + self.retry_base * 2 ** (attempts - 1), server, row["identity"]))
            db.execute("UPDATE scans SET phase=? WHERE server=?", (reason, server))
        logger.warning("Media scan deferred/failed reason=%s batch=%d", reason, len(rows))

    def tick(self):
        with dispatch_lock(self.path.with_suffix(".lock")) as acquired:
            if not acquired:
                return
            self._tick()

    @staticmethod
    def _scan_task(client):
        try:
            return client.library_scan_task()
        except Exception:
            return None

    def _verify_submitted(self, server):
        now = self.clock()
        with self.db() as db:
            rows = db.execute("SELECT * FROM media WHERE server=? AND state='submitted' AND due<=? LIMIT 128", (server, now)).fetchall()
        for row in rows:
            try:
                present = self.recognized(json.loads(row["evidence"]))
            except Exception:
                present = None
            if self.target()[1] != server:
                return
            state = "recognized" if present is True else "failed" if now - row["submitted_at"] >= 1800 else "submitted"
            reason = "" if present is True else "media_not_detected" if present is False else "recognition_unavailable"
            with self.db() as db:
                db.execute("UPDATE media SET state=?,reason=?,due=? WHERE server=? AND identity=?", (state, reason, now + 60, server, row["identity"]))
            if state != "submitted":
                logger.info("Media recognition state=%s source=%s reason=%s", state, row["source"], reason)

    def _tick(self):
        client, server = self.target()
        if not server:
            return
        self._verify_submitted(server)
        now = self.clock()
        with self.db() as db:
            # A crashed dispatch is ambiguous; respect its durable cooldown and
            # retry budget rather than immediately replaying the POST on restart.
            db.execute("UPDATE media SET state='pending' WHERE server=? AND state='dispatching' AND due<=? AND attempts<?", (server, now, self.max_attempts))
            db.execute("UPDATE media SET state='failed',reason='dispatch_outcome_unknown' WHERE server=? AND state='dispatching' AND due<=? AND attempts>=?", (server, now, self.max_attempts))
            db.execute("UPDATE media SET state='failed',reason='pending_expired' WHERE state='pending' AND created<?", (now - self.max_age,))
            # Retain identity tombstones: recurring status polls must never turn
            # a completed/failed file back into an endless scan loop.
            ready = db.execute("SELECT 1 FROM media WHERE server=? AND state='pending' AND due<=? LIMIT 1", (server, now)).fetchone()
            rows = db.execute("SELECT * FROM media WHERE server=? AND state='pending' AND (due<=? OR attempts=0) ORDER BY created LIMIT 128", (server, now)).fetchall() if ready else []
            scan = db.execute("SELECT * FROM scans WHERE server=?", (server,)).fetchone()
        if not rows:
            return
        if scan and max(scan["last_start"], scan["last_attempt"]) and now < max(scan["last_start"], scan["last_attempt"]) + self.cooldown:
            self._state(server, "cooldown")
            return
        # The Jellyfin endpoint is checked before any expensive local probing.
        if getattr(client, "provider", "jellyfin") != "plex":
            task = self._scan_task(client)
            if task is None:
                self._failed(server, rows, "scan_status_unavailable")
                return
            if task["State"] != "Idle":
                self._state(server, "server_scan_running")
                return
            if task.get("last_start", 0) and now < task["last_start"] + self.cooldown:
                self._state(server, "server_scan_cooldown")
                return
        else:
            task = None  # Existing Plex client remains supported, with cooldown.
        valid = []
        for row in rows:
            try:
                _, before = file_identity(row["path"])
                okay = before == row["signature"] and self.validate(row["path"])
                _, after = file_identity(row["path"])
                okay = okay and before == after
            except Exception:
                okay = False
            if okay:
                valid.append(row)
            else:
                with self.db() as db:
                    db.execute("UPDATE media SET state='failed',reason='invalid_or_changed_media' WHERE server=? AND identity=?", (server, row["identity"]))
                logger.warning("Media scan rejected source=%s reason=invalid_or_changed_media", row["source"])
        if not valid:
            return
        # Recheck after probing: Jellyfin may have started a scheduled scan while
        # ffprobe ran. Never cancel or restart that task.
        if task is not None:
            task = self._scan_task(client)
            if task is None:
                self._failed(server, valid, "scan_status_unavailable")
                return
            if task["State"] != "Idle":
                self._state(server, "server_scan_running")
                return
            if task.get("last_start", 0) and now < task["last_start"] + self.cooldown:
                self._state(server, "server_scan_cooldown")
                return
        if self.target()[1] != server or self.stop_event.is_set():
            return
        final = []
        for row in valid:
            try:
                if file_identity(row["path"])[1] == row["signature"]:
                    final.append(row)
            except (ValueError, OSError):
                pass
        valid = final
        if not valid:
            return
        now = self.clock()
        with self.db() as db:
            db.execute("UPDATE scans SET last_attempt=?,phase='dispatching' WHERE server=?", (now, server))
            for row in valid:
                db.execute("UPDATE media SET state='dispatching',attempts=attempts+1,due=? WHERE server=? AND identity=?", (now + self.cooldown, server, row["identity"]))
        try:
            accepted = client.start_library_scan(task["Id"]) if task is not None else client.refresh_library()
        except Exception:
            accepted = False  # Never log exception text/URLs/credentials.
        with self.db() as db:
            for row in valid:
                attempts = row["attempts"] + 1
                result = "submitted" if accepted else "failed" if attempts >= self.max_attempts else "pending"
                db.execute("UPDATE media SET state=?,reason=?,due=?,submitted_at=? WHERE server=? AND identity=?",
                           (result, "" if accepted else "dispatch_failed", now + 120 if accepted else now + max(self.cooldown, self.retry_base * 2 ** (attempts - 1)), now if accepted else 0, server, row["identity"]))
            if accepted:
                db.execute("UPDATE scans SET last_start=? WHERE server=?", (now, server))
            db.execute("UPDATE scans SET phase=?,submitted=submitted+?,avoided=avoided+? WHERE server=?",
                       ("submitted" if accepted else "dispatch_failed", int(accepted), max(0, len(valid)-1) if accepted else 0, server))
        logger.info("Media scan %s sources=%s batch=%d", "submitted" if accepted else "failed", ",".join(sorted({row["source"] for row in valid})), len(valid))
        if accepted:
            try:
                self.on_submitted()
            except Exception:
                logger.warning("Media scan cache reconciliation failed")

    def snapshot(self):
        _, server = self.target()
        with self.db() as db:
            scan = db.execute("SELECT * FROM scans WHERE server=?", (server,)).fetchone()
            counts = {row["state"]: row["n"] for row in db.execute("SELECT state,count(*) n FROM media WHERE server=? GROUP BY state", (server,))}
            failures = [dict(row) for row in db.execute("SELECT source,reason,attempts FROM media WHERE server=? AND state='failed' ORDER BY created DESC LIMIT 10", (server,))]
        return {**({key: scan[key] for key in ("last_start", "last_attempt", "phase", "submitted", "avoided", "requests")} if scan else {"phase": "idle"}), "counts": counts, "recent_failures": failures}

    def start(self):
        with self.guard:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._run, name="media-scan-coordinator", daemon=True)
            self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.tick()
            except Exception:
                logger.warning("Media scan coordinator unavailable; pending state retained")
            self.wake.wait(15)
            self.wake.clear()

    def stop(self):
        self.stop_event.set(); self.wake.set()
        thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
