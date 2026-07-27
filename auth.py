"""
Anmeldung: Passwort-Hashing, Sitzungsverwaltung und Brute-Force-Schutz.

Bewusst ohne neue Abhängigkeit gebaut (nur `hashlib`/`hmac`/`secrets` aus der
Standardbibliothek), damit `start.sh` auf dem NAS nichts zusätzlich
installieren muss.

Aufteilung:
  * `hash_password` / `verify_password` – PBKDF2-HMAC-SHA256 mit Zufallssalz.
  * `SessionStore` – serverseitige Sitzungen. Der Browser bekommt nur ein
    Zufallstoken im Cookie; auf der Platte liegt ausschließlich dessen
    SHA-256-Hash. Ein gestohlenes Backup der Sitzungsdatei erlaubt damit keine
    Übernahme einer laufenden Sitzung.
  * `LoginGuard` – Fehlversuchszähler je IP, sperrt nach zu vielen Fehlschlägen.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Passwörter
# ---------------------------------------------------------------------------
HASH_SCHEME = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 210_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256
MIN_USERNAME_LENGTH = 3
MAX_USERNAME_LENGTH = 64


def _b64encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str, iterations: int = DEFAULT_ITERATIONS) -> str:
    """Erzeugt `pbkdf2_sha256$<runden>$<salz>$<hash>` (alles base64)."""
    if not isinstance(password, str) or not password:
        raise ValueError("Passwort darf nicht leer sein.")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_SCHEME}${iterations}${_b64encode(salt)}${_b64encode(derived)}"


def verify_password(password: str, stored: str) -> bool:
    """Prüft ein Passwort gegen einen gespeicherten Hash (zeitkonstant)."""
    if not password or not stored:
        return False
    try:
        scheme, raw_iterations, raw_salt, raw_hash = stored.split("$", 3)
        if scheme != HASH_SCHEME:
            return False
        iterations = int(raw_iterations)
        salt = base64.b64decode(raw_salt, validate=True)
        expected = base64.b64decode(raw_hash, validate=True)
    except (ValueError, TypeError, binascii.Error):
        return False
    if iterations <= 0 or not salt or not expected:
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived, expected)


def normalize_username(value: str) -> str:
    return str(value or "").strip()


def validate_username(value: str) -> str:
    """Gibt den bereinigten Benutzernamen zurück oder wirft ValueError."""
    username = normalize_username(value)
    if len(username) < MIN_USERNAME_LENGTH:
        raise ValueError(
            f"Der Benutzername braucht mindestens {MIN_USERNAME_LENGTH} Zeichen."
        )
    if len(username) > MAX_USERNAME_LENGTH:
        raise ValueError(
            f"Der Benutzername darf höchstens {MAX_USERNAME_LENGTH} Zeichen haben."
        )
    # settings.ini ist ein simples key=value-Format: Zeilenumbrüche und "="
    # würden die Datei zerlegen.
    if any(char in username for char in "\r\n=") or username != username.strip():
        raise ValueError("Der Benutzername enthält unerlaubte Zeichen.")
    return username


def validate_password(value: str) -> str:
    """Gibt das Passwort zurück oder wirft ValueError mit Begründung."""
    password = str(value or "")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Das Passwort braucht mindestens {MIN_PASSWORD_LENGTH} Zeichen."
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(
            f"Das Passwort darf höchstens {MAX_PASSWORD_LENGTH} Zeichen haben."
        )
    if password.strip() != password:
        raise ValueError("Das Passwort darf nicht mit einem Leerzeichen beginnen oder enden.")
    return password


# ---------------------------------------------------------------------------
# Sitzungen
# ---------------------------------------------------------------------------
SESSION_COOKIE_NAME = "royal_session"
SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_TTL_SECONDS = 30 * 24 * 60 * 60   # 30 Tage
DEFAULT_SESSION_IDLE_SECONDS = 14 * 24 * 60 * 60  # 14 Tage ohne Aktivität
MAX_SESSIONS = 50


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    """Serverseitige Sitzungen, überlebt einen Neustart des Containers.

    Ohne Persistenz würde jedes Update (der Updater startet den Prozess neu)
    alle angemeldeten Geräte abmelden – bei einem Dienst, der sich selbst
    aktualisiert, wäre das ein täglicher Störfaktor.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
        idle_seconds: int = DEFAULT_SESSION_IDLE_SECONDS,
        max_sessions: int = MAX_SESSIONS,
    ):
        self._path = Path(path) if path else None
        self._ttl = max(60, int(ttl_seconds))
        self._idle = max(60, int(idle_seconds))
        self._max_sessions = max(1, int(max_sessions))
        self._lock = threading.RLock()
        self._sessions: Dict[str, dict] = {}
        self._load()

    # -- Persistenz ---------------------------------------------------------
    def _load(self) -> None:
        if not self._path or not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Sitzungsdatei nicht lesbar (%s): %s", self._path, exc)
            return
        if not isinstance(raw, dict):
            return
        entries = raw.get("sessions")
        if not isinstance(entries, dict):
            return
        now = time.time()
        with self._lock:
            for fingerprint, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                created = float(entry.get("created") or 0)
                last_seen = float(entry.get("last_seen") or created)
                if not created or self._is_expired(created, last_seen, now):
                    continue
                self._sessions[str(fingerprint)] = {
                    "created": created,
                    "last_seen": last_seen,
                    "label": str(entry.get("label") or ""),
                }

    def _save_locked(self) -> None:
        if not self._path:
            return
        payload = {"version": 1, "sessions": self._sessions}
        tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
            try:
                self._path.chmod(0o600)
            except OSError:
                pass
        except Exception as exc:
            logger.warning("Sitzungen konnten nicht gespeichert werden: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # -- Ablauf -------------------------------------------------------------
    def _is_expired(self, created: float, last_seen: float, now: float) -> bool:
        return (now - created) > self._ttl or (now - last_seen) > self._idle

    def _purge_locked(self, now: float) -> bool:
        stale = [
            fingerprint
            for fingerprint, entry in self._sessions.items()
            if self._is_expired(entry["created"], entry["last_seen"], now)
        ]
        for fingerprint in stale:
            self._sessions.pop(fingerprint, None)
        return bool(stale)

    # -- API ----------------------------------------------------------------
    def create(self, label: str = "") -> str:
        """Legt eine Sitzung an und gibt das Klartext-Token für das Cookie zurück."""
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        now = time.time()
        with self._lock:
            self._purge_locked(now)
            if len(self._sessions) >= self._max_sessions:
                # Älteste Sitzung weichen lassen, damit ein Gerät mit
                # Cookie-Verlust den Speicher nicht unbegrenzt füllt.
                oldest = min(self._sessions.items(), key=lambda item: item[1]["last_seen"])
                self._sessions.pop(oldest[0], None)
            self._sessions[_token_fingerprint(token)] = {
                "created": now,
                "last_seen": now,
                "label": str(label or "")[:120],
            }
            self._save_locked()
        return token

    def validate(self, token: str) -> bool:
        """Prüft ein Token und schreibt bei Erfolg den Zeitstempel fort."""
        if not token:
            return False
        fingerprint = _token_fingerprint(token)
        now = time.time()
        with self._lock:
            entry = self._sessions.get(fingerprint)
            if entry is None:
                return False
            if self._is_expired(entry["created"], entry["last_seen"], now):
                self._sessions.pop(fingerprint, None)
                self._save_locked()
                return False
            # Nicht bei jedem Request schreiben: die Oberfläche fragt im
            # Sekundentakt Status ab, das wären sonst tausende Schreibzugriffe
            # pro Stunde auf dem NAS-Volume.
            previous = entry["last_seen"]
            entry["last_seen"] = now
            if (now - previous) > 3600:
                self._save_locked()
            return True

    def revoke(self, token: str) -> bool:
        if not token:
            return False
        fingerprint = _token_fingerprint(token)
        with self._lock:
            removed = self._sessions.pop(fingerprint, None) is not None
            if removed:
                self._save_locked()
            return removed

    def revoke_all(self, keep_token: str = "") -> int:
        """Meldet alle Sitzungen ab; `keep_token` bleibt optional bestehen."""
        keep = _token_fingerprint(keep_token) if keep_token else ""
        with self._lock:
            removed = [key for key in self._sessions if key != keep]
            for key in removed:
                self._sessions.pop(key, None)
            self._save_locked()
            return len(removed)

    def count(self) -> int:
        with self._lock:
            self._purge_locked(time.time())
            return len(self._sessions)


# ---------------------------------------------------------------------------
# Brute-Force-Schutz
# ---------------------------------------------------------------------------
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_ATTEMPT_WINDOW = 300.0
DEFAULT_LOCKOUT_SECONDS = 300.0


class LoginGuard:
    """Zählt Fehlanmeldungen je Herkunfts-IP und sperrt sie zeitweise."""

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        window_seconds: float = DEFAULT_ATTEMPT_WINDOW,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
    ):
        self._max_attempts = max(1, int(max_attempts))
        self._window = float(window_seconds)
        self._lockout = float(lockout_seconds)
        self._lock = threading.Lock()
        self._attempts: Dict[str, list] = {}
        self._locked_until: Dict[str, float] = {}

    def retry_after(self, key: str) -> int:
        """Verbleibende Sperrzeit in Sekunden (0 = nicht gesperrt)."""
        if not key:
            return 0
        now = time.time()
        with self._lock:
            until = self._locked_until.get(key, 0.0)
            if until <= now:
                if key in self._locked_until:
                    self._locked_until.pop(key, None)
                return 0
            return int(until - now) + 1

    def register_failure(self, key: str) -> int:
        """Verbucht einen Fehlversuch; gibt die Sperrzeit zurück (0 = frei)."""
        if not key:
            return 0
        now = time.time()
        with self._lock:
            timestamps = [
                stamp for stamp in self._attempts.get(key, []) if (now - stamp) < self._window
            ]
            timestamps.append(now)
            self._attempts[key] = timestamps
            if len(timestamps) >= self._max_attempts:
                self._locked_until[key] = now + self._lockout
                self._attempts.pop(key, None)
                return int(self._lockout)
            return 0

    def register_success(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            self._attempts.pop(key, None)
            self._locked_until.pop(key, None)

    def remaining_attempts(self, key: str) -> int:
        if not key:
            return self._max_attempts
        now = time.time()
        with self._lock:
            timestamps = [
                stamp for stamp in self._attempts.get(key, []) if (now - stamp) < self._window
            ]
            return max(0, self._max_attempts - len(timestamps))


class RateLimiter:
    """Einfaches Anfragebudget je Schlüssel für Endpunkte ohne Anmeldung."""

    def __init__(self, max_requests: int, window_seconds: float):
        self._max_requests = max(1, int(max_requests))
        self._window = float(window_seconds)
        self._lock = threading.Lock()
        self._hits: Dict[str, list] = {}

    def allow(self, key: str) -> bool:
        if not key:
            return True
        now = time.time()
        with self._lock:
            timestamps = [
                stamp for stamp in self._hits.get(key, []) if (now - stamp) < self._window
            ]
            if len(timestamps) >= self._max_requests:
                self._hits[key] = timestamps
                return False
            timestamps.append(now)
            self._hits[key] = timestamps
            # Gelegentlich aufräumen, damit der Speicher bei wechselnden IPs
            # nicht unbegrenzt wächst.
            if len(self._hits) > 2048:
                for stale_key in [
                    existing
                    for existing, stamps in self._hits.items()
                    if not stamps or (now - stamps[-1]) > self._window
                ]:
                    self._hits.pop(stale_key, None)
            return True
