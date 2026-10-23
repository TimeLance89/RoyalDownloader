"""Signed, installation-independent Royal announcements.

The private signing key belongs ONLY on the official publisher installation.
Every recipient trusts the pinned public key, never a remote replacement.
All external I/O is synchronous; the router dispatches it to a worker thread.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from core import egress_requests as outbound_requests

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, Encoding, PublicFormat

from core.runtime_paths import data_dir

OFFICIAL_ORIGIN = "https://royal-downloader.de"
PUBLIC_KEY_B64 = "w1yMxgVSxM33W/MOU6IHGW/36yrYjLP9FNy0azL5di8="
MAX_ITEMS = 75
POLL_SECONDS = 300
_lock = threading.RLock()
_last_poll = 0.0


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify(payload: dict, signature: str) -> bool:
    try:
        if not isinstance(payload, dict) or len(_canonical(payload)) > 8192:
            return False
        expected = base64.b64decode(signature, validate=True)
        Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLIC_KEY_B64)).verify(expected, _canonical(payload))
        return _valid_payload(payload)
    except Exception:  # Includes InvalidSignature and malformed third-party input.
        return False


def _valid_payload(payload: dict) -> bool:
    return (
        payload.get("version") == 1
        and isinstance(payload.get("id"), str) and len(payload["id"]) == 36
        and str(uuid.UUID(payload["id"])) == payload["id"]
        and isinstance(payload.get("revision"), int) and 1 <= payload["revision"] <= 1000000
        and payload.get("category") in {"news", "event", "important"}
        and isinstance(payload.get("title"), str) and 1 <= len(payload["title"]) <= 120
        and isinstance(payload.get("body"), str) and 1 <= len(payload["body"]) <= 3000
        and isinstance(payload.get("created_at"), int) and payload["created_at"] > 0
        and isinstance(payload.get("expires_at"), int) and payload["expires_at"] >= 0
        and isinstance(payload.get("revoked"), bool)
    )


def _db_path() -> Path:
    return data_dir() / "FilmeDownloader" / "announcements.sqlite3"


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        con = sqlite3.connect(path, timeout=3)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=3000")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY, payload TEXT NOT NULL, signature TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS local_read (
                message_id TEXT NOT NULL, user_id TEXT NOT NULL,
                PRIMARY KEY (message_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS receipts (
                message_id TEXT NOT NULL, installation TEXT NOT NULL, profile TEXT NOT NULL,
                delivered INTEGER NOT NULL DEFAULT 0, read_at INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (message_id, installation, profile)
            );
            CREATE TABLE IF NOT EXISTS receipt_outbox (
                message_id TEXT NOT NULL, profile TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY (message_id, profile, kind)
            );
            CREATE TABLE IF NOT EXISTS receipt_sent (
                message_id TEXT NOT NULL, profile TEXT NOT NULL, kind TEXT NOT NULL,
                PRIMARY KEY (message_id, profile, kind)
            );
        """)
        con.commit()
        if os.name == "posix":
            os.chmod(path, 0o600)
        return con


def _config(key: str, default: str = "") -> str:
    with _lock, _connect() as db:
        row = db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def _set_config(key: str, value: str):
    with _lock, _connect() as db:
        db.execute("INSERT OR REPLACE INTO config(key, value) VALUES (?,?)", (key, value))
        db.commit()


def enabled() -> bool:
    return _config("enabled", "1") == "1"


def set_enabled(value: bool):
    _set_config("enabled", "1" if value else "0")


def installation_id() -> str:
    with _lock, _connect() as db:
        row = db.execute("SELECT value FROM config WHERE key='installation_id'").fetchone()
        if row:
            return row["value"]
        identity = str(uuid.uuid4())
        db.execute("INSERT INTO config(key, value) VALUES('installation_id', ?)", (identity,))
        db.commit()
        return identity


def _profile_token(user_id: str) -> str:
    return hashlib.sha256((installation_id() + ":" + user_id).encode()).hexdigest()[:32]


def _signing_key():
    if os.environ.get("ROYAL_ANNOUNCEMENTS_PUBLISHER") != "1":
        return None
    path = os.environ.get("ROYAL_ANNOUNCEMENTS_PRIVATE_KEY_FILE", "").strip()
    if not path or not os.environ.get("ROYAL_ANNOUNCEMENTS_OWNER_USER_ID", "").strip():
        return None
    try:
        key = load_pem_private_key(Path(path).read_bytes(), password=None)
        pub = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if not secrets.compare_digest(pub, base64.b64decode(PUBLIC_KEY_B64)):
            return None
        return key
    except (OSError, TypeError, ValueError):
        return None


def publisher_ready() -> bool:
    return _signing_key() is not None


def is_publisher_owner(user: dict | None) -> bool:
    return bool(
        user and user.get("enabled") and user.get("role") == "admin"
        and str(user.get("id")) == os.environ.get("ROYAL_ANNOUNCEMENTS_OWNER_USER_ID", "")
        and publisher_ready()
    )


def _messages() -> list[dict]:
    with _lock, _connect() as db:
        rows = db.execute("SELECT payload,signature FROM messages ORDER BY rowid DESC LIMIT ?", (MAX_ITEMS,)).fetchall()
    result = []
    for row in rows:
        try:
            payload = json.loads(row["payload"])
            if verify(payload, row["signature"]):
                result.append({"payload": payload, "signature": row["signature"]})
        except (json.JSONDecodeError, TypeError):
            continue
    return result


def _save_signed(items: list[dict]):
    with _lock, _connect() as db:
        for item in items:
            payload, signature = item.get("payload"), item.get("signature")
            if not verify(payload, signature):
                continue
            old = db.execute("SELECT payload FROM messages WHERE id=?", (payload["id"],)).fetchone()
            if old:
                try:
                    old_revision = int(json.loads(old["payload"]).get("revision", 0))
                except (ValueError, TypeError):
                    old_revision = 0
                if old_revision >= payload["revision"]:
                    continue
            db.execute(
                "INSERT OR REPLACE INTO messages (id,payload,signature) VALUES (?,?,?)",
                (payload["id"], _canonical(payload).decode(), signature),
            )
        db.commit()


def _get_json(path: str) -> dict:
    with outbound_requests.get(
        OFFICIAL_ORIGIN + path, timeout=3, allow_redirects=False, stream=True,
        headers={"Accept": "application/json", "User-Agent": "RoyalDownloader-Announcements/1"},
    ) as response:
        if response.status_code != 200:
            raise ValueError("Ungültige Announcement-Antwort")
        if int(response.headers.get("Content-Length", "0")) > 1000000:
            raise ValueError("Announcement-Antwort zu groß")
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=16384):
            size += len(chunk)
            if size > 1000000:
                raise ValueError("Announcement-Antwort zu groß")
            chunks.append(chunk)
        return json.loads(b"".join(chunks))


def _post_receipt(items: list[dict]):
    body = {"installation": installation_id(), "items": items}
    with outbound_requests.post(
        OFFICIAL_ORIGIN + "/api/public/announcements/receipts",
        json=body, timeout=3, allow_redirects=False,
        headers={"User-Agent": "RoyalDownloader-Announcements/1"},
    ) as response:
        if response.status_code != 200:
            raise ValueError("Empfangsbestätigung fehlgeschlagen")


def _queue_receipt(message_id: str, user_id: str, kind: str):
    with _lock, _connect() as db:
        token = _profile_token(user_id)
        already_sent = db.execute("SELECT 1 FROM receipt_sent WHERE message_id=? AND profile=? AND kind=?", (message_id, token, kind)).fetchone()
        if already_sent:
            return
        db.execute(
            "INSERT OR IGNORE INTO receipt_outbox(message_id,profile,kind) VALUES(?,?,?)",
            (message_id, token, kind),
        )
        db.commit()


def _flush_receipts():
    with _lock, _connect() as db:
        rows = db.execute("SELECT message_id,profile,kind FROM receipt_outbox LIMIT 50").fetchall()
    if not rows:
        return
    items = [{"id": r["message_id"], "profile": r["profile"], "kind": r["kind"]} for r in rows]
    _post_receipt(items)
    with _lock, _connect() as db:
        triples = [(r["message_id"], r["profile"], r["kind"]) for r in rows]
        db.executemany("INSERT OR IGNORE INTO receipt_sent(message_id,profile,kind) VALUES(?,?,?)", triples)
        db.executemany("DELETE FROM receipt_outbox WHERE message_id=? AND profile=? AND kind=?", triples)
        db.commit()


def sync():
    global _last_poll
    if not enabled() or publisher_ready():
        return
    with _lock:
        if _last_poll > 0 and time.monotonic() - _last_poll < POLL_SECONDS:
            return
        _last_poll = time.monotonic()
    try:
        document = _get_json("/api/public/announcements/feed")
        items = document.get("items")
        if not isinstance(items, list) or len(items) > MAX_ITEMS:
            raise ValueError("Ungültiges Feed-Format")
        if any(not isinstance(x, dict) or not verify(x.get("payload"), x.get("signature")) for x in items):
            raise ValueError("Ungültige Signatur im Feed")
        _save_signed(items)
    except (OSError, outbound_requests.exceptions.RequestException, ValueError, TypeError, json.JSONDecodeError):
        pass  # Retain verified offline cache; never trust a partial update.
    try:
        _flush_receipts()
    except (OSError, outbound_requests.exceptions.RequestException, ValueError):
        pass


def inbox(user_id: str) -> dict:
    if not enabled():
        return {"enabled": False, "items": []}
    sync()
    now = int(time.time())
    with _lock, _connect() as db:
        read_ids = {r["message_id"] for r in db.execute("SELECT message_id FROM local_read WHERE user_id=?", (user_id,))}
    results = []
    for item in _messages():
        p = item["payload"]
        if p["revoked"] or (p["expires_at"] and p["expires_at"] <= now):
            continue
        if p["id"] not in read_ids:
            _queue_receipt(p["id"], user_id, "delivered")
        results.append({**p, "read": p["id"] in read_ids})
    return {"enabled": True, "items": results}


def mark_read(user_id: str, message_id: str):
    if not enabled():
        raise ValueError("Ankündigungen sind deaktiviert")
    matching = [item for item in _messages() if item["payload"]["id"] == message_id]
    if not matching or matching[0]["payload"]["revoked"]:
        raise ValueError("Unbekannte Ankündigung")
    with _lock, _connect() as db:
        db.execute("INSERT OR IGNORE INTO local_read(message_id,user_id) VALUES (?,?)", (message_id, user_id))
        db.commit()
    _queue_receipt(message_id, user_id, "read")


def publish(title: str, body: str, category: str, expires_at: int = 0) -> dict:
    key = _signing_key()
    if not key:
        raise PermissionError("Publisher nicht eingerichtet")
    now = int(time.time())
    payload = {
        "version": 1, "id": str(uuid.uuid4()), "revision": 1,
        "title": title.strip(), "body": body.strip(), "category": category,
        "created_at": now, "expires_at": expires_at, "revoked": False,
    }
    if not _valid_payload(payload) or len(_canonical(payload)) > 8192 or (expires_at and expires_at <= now):
        raise ValueError("Ungültige Ankündigung")
    signed = {"payload": payload, "signature": base64.b64encode(key.sign(_canonical(payload))).decode()}
    _save_signed([signed])
    return payload


def revoke(message_id: str):
    key = _signing_key()
    if not key:
        raise PermissionError("Publisher nicht eingerichtet")
    item = next((x for x in _messages() if x["payload"]["id"] == message_id), None)
    if not item:
        raise ValueError("Unbekannte Ankündigung")
    payload = {**item["payload"], "revision": item["payload"]["revision"] + 1, "revoked": True}
    _save_signed([{"payload": payload, "signature": base64.b64encode(key.sign(_canonical(payload))).decode()}])


def feed():
    if not publisher_ready():
        raise PermissionError("Publisher nicht eingerichtet")
    return {"items": _messages()}


def accept_receipts(installation: str, items: list[dict]):
    if not publisher_ready():
        raise PermissionError("Publisher nicht eingerichtet")
    if len(installation) != 36 or str(uuid.UUID(installation)) != installation or len(items) > 50:
        raise ValueError("Ungültige Empfangsbestätigung")
    valid_ids = {i["payload"]["id"] for i in _messages()}
    with _lock, _connect() as db:
        for item in items:
            mid, profile, kind = item.get("id"), item.get("profile"), item.get("kind")
            if mid not in valid_ids or not isinstance(profile, str) or len(profile) != 32 or not all(c in "0123456789abcdef" for c in profile) or kind not in {"delivered", "read"}:
                continue
            now = int(time.time())
            db.execute(
                """INSERT INTO receipts(message_id,installation,profile,delivered,read_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(message_id,installation,profile) DO UPDATE SET
                   delivered=MAX(receipts.delivered,excluded.delivered),
                   read_at=MAX(receipts.read_at,excluded.read_at)""",
                (mid, installation, profile, now, now if kind == "read" else 0),
            )
        db.commit()


def statistics():
    with _lock, _connect() as db:
        all_receipts = db.execute(
            """SELECT message_id, COUNT(DISTINCT installation) AS installations,
               COUNT(*) AS profiles, SUM(CASE WHEN read_at>0 THEN 1 ELSE 0 END) AS read_profiles
               FROM receipts GROUP BY message_id"""
        ).fetchall()
    counts = {r["message_id"]: {"installations": r["installations"], "delivered_profiles": r["profiles"], "read_profiles": r["read_profiles"]} for r in all_receipts}
    return [{**item["payload"], "stats": counts.get(item["payload"]["id"], {"installations": 0, "delivered_profiles": 0, "read_profiles": 0})} for item in _messages()]
