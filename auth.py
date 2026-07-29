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
import math
import os
import secrets
import threading
import time
from collections import OrderedDict
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
SESSION_KIND_WEB = "web"
SESSION_KIND_MOBILE = "mobile"
SESSION_KINDS = frozenset({SESSION_KIND_WEB, SESSION_KIND_MOBILE})


class SessionPersistenceError(RuntimeError):
    """Eine sicherheitsrelevante Sitzungsänderung konnte nicht gespeichert werden."""


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
            loaded = []
            for fingerprint, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                try:
                    created = float(entry.get("created") or 0)
                    last_seen = float(entry.get("last_seen") or created)
                except (TypeError, ValueError, OverflowError):
                    continue
                if (
                    not created
                    or not math.isfinite(created)
                    or not math.isfinite(last_seen)
                    or self._is_expired(created, last_seen, now)
                ):
                    continue
                # Dateien aus Version 1 besitzen noch kein `kind`. Sie stammen
                # ausschließlich von Browser-Logins und werden deshalb bewusst
                # als Web-Sitzung migriert, nie als privilegiertes Mobile-Token.
                kind = str(entry.get("kind") or SESSION_KIND_WEB)
                if kind not in SESSION_KINDS:
                    kind = SESSION_KIND_WEB
                loaded.append((str(fingerprint), {
                    "created": created,
                    "last_seen": last_seen,
                    "label": str(entry.get("label") or ""),
                    "kind": kind,
                    "_persisted_last_seen": last_seen,
                }))
            # Auch eine manipulierte oder beschädigte Datei darf das konfigurierte
            # Speicherlimit nicht umgehen. Die zuletzt aktiven Sitzungen bleiben.
            loaded.sort(key=lambda item: item[1]["last_seen"], reverse=True)
            self._sessions.update(loaded[:self._max_sessions])

    def _save_locked(self) -> None:
        if not self._path:
            return
        payload = {
            "version": 2,
            "sessions": {
                fingerprint: {
                    key: value
                    for key, value in entry.items()
                    if not key.startswith("_")
                }
                for fingerprint, entry in self._sessions.items()
            },
        }
        tmp = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self._path)
            for entry in self._sessions.values():
                entry["_persisted_last_seen"] = entry["last_seen"]
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
            raise SessionPersistenceError(
                "Sitzungen konnten nicht dauerhaft gespeichert werden."
            ) from exc

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
    def create(self, label: str = "", kind: str = SESSION_KIND_WEB) -> str:
        """Legt eine Sitzung an und gibt das Klartext-Token für das Cookie zurück."""
        if kind not in SESSION_KINDS:
            raise ValueError("Unbekannter Sitzungstyp.")
        token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        now = time.time()
        with self._lock:
            previous = {key: dict(entry) for key, entry in self._sessions.items()}
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
                "kind": kind,
                "_persisted_last_seen": now,
            }
            try:
                self._save_locked()
            except SessionPersistenceError:
                self._sessions = previous
                raise
        return token

    def validate(
        self,
        token: str,
        kind: Optional[str] = None,
        *,
        touch: bool = True,
    ) -> bool:
        """Prüft ein Token und schreibt bei Erfolg den Zeitstempel fort."""
        if not token:
            return False
        if kind is not None and kind not in SESSION_KINDS:
            return False
        fingerprint = _token_fingerprint(token)
        now = time.time()
        with self._lock:
            entry = self._sessions.get(fingerprint)
            if entry is None:
                return False
            if kind is not None and entry.get("kind", SESSION_KIND_WEB) != kind:
                return False
            if self._is_expired(entry["created"], entry["last_seen"], now):
                self._sessions.pop(fingerprint, None)
                try:
                    self._save_locked()
                except SessionPersistenceError:
                    # Der Eintrag ist anhand seiner persistierten Zeitwerte auch
                    # nach einem Neustart abgelaufen. Authentifizierung bleibt
                    # deshalb sicher abgewiesen, selbst wenn Aufräumen scheitert.
                    pass
                return False
            if not touch:
                return True
            # Nicht bei jedem Request schreiben: die Oberfläche fragt im
            # Sekundentakt Status ab, das wären sonst tausende Schreibzugriffe
            # pro Stunde auf dem NAS-Volume.
            entry["last_seen"] = now
            if (now - entry.get("_persisted_last_seen", 0)) > 3600:
                try:
                    self._save_locked()
                except SessionPersistenceError:
                    # Ein Checkpoint-Fehler darf eine aktuell gültige Sitzung
                    # nicht mitten im Request in einen Serverfehler verwandeln.
                    pass
            return True

    def revoke(self, token: str, kind: Optional[str] = None) -> bool:
        if not token:
            return False
        if kind is not None and kind not in SESSION_KINDS:
            return False
        fingerprint = _token_fingerprint(token)
        with self._lock:
            entry = self._sessions.get(fingerprint)
            if entry is None:
                return False
            if kind is not None and entry.get("kind", SESSION_KIND_WEB) != kind:
                return False
            removed = self._sessions.pop(fingerprint)
            try:
                self._save_locked()
            except SessionPersistenceError:
                self._sessions[fingerprint] = removed
                raise
            return True

    def revoke_all(self, keep_token: str = "", kind: Optional[str] = None) -> int:
        """Meldet alle Sitzungen ab; `keep_token` bleibt optional bestehen."""
        if kind is not None and kind not in SESSION_KINDS:
            raise ValueError("Unbekannter Sitzungstyp.")
        keep = _token_fingerprint(keep_token) if keep_token else ""
        with self._lock:
            removed = {
                key: entry
                for key, entry in self._sessions.items()
                if key != keep
                and (kind is None or entry.get("kind", SESSION_KIND_WEB) == kind)
            }
            if not removed:
                return 0
            for key in removed:
                self._sessions.pop(key, None)
            try:
                self._save_locked()
            except SessionPersistenceError:
                self._sessions.update(removed)
                raise
            return len(removed)

    def count(self, kind: Optional[str] = None) -> int:
        if kind is not None and kind not in SESSION_KINDS:
            return 0
        with self._lock:
            self._purge_locked(time.time())
            return sum(
                1
                for entry in self._sessions.values()
                if kind is None or entry.get("kind", SESSION_KIND_WEB) == kind
            )


# ---------------------------------------------------------------------------
# Brute-Force-Schutz
# ---------------------------------------------------------------------------
DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_ATTEMPT_WINDOW = 300.0
DEFAULT_LOCKOUT_SECONDS = 300.0
DEFAULT_MAX_TRACKED_LOGIN_KEYS = 4096


class LoginGuard:
    """Zählt Fehlanmeldungen je Herkunfts-IP und sperrt sie zeitweise."""

    def __init__(
        self,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        window_seconds: float = DEFAULT_ATTEMPT_WINDOW,
        lockout_seconds: float = DEFAULT_LOCKOUT_SECONDS,
        max_tracked_keys: int = DEFAULT_MAX_TRACKED_LOGIN_KEYS,
    ):
        self._max_attempts = max(1, int(max_attempts))
        self._window = float(window_seconds)
        self._lockout = float(lockout_seconds)
        self._max_tracked_keys = max(16, int(max_tracked_keys))
        self._lock = threading.Lock()
        self._attempts: Dict[str, list] = {}
        self._locked_until: Dict[str, float] = {}
        self._key_order: OrderedDict[str, None] = OrderedDict()
        self._last_cleanup = 0.0

    def _touch_key_locked(self, key: str) -> None:
        self._key_order.pop(key, None)
        self._key_order[key] = None
        while len(self._key_order) > self._max_tracked_keys:
            oldest, _ = self._key_order.popitem(last=False)
            self._attempts.pop(oldest, None)
            self._locked_until.pop(oldest, None)

    def _cleanup_locked(self, now: float) -> None:
        if (
            (now - self._last_cleanup) < 60
            and len(self._key_order) <= self._max_tracked_keys
        ):
            return
        for key, timestamps in list(self._attempts.items()):
            active = [stamp for stamp in timestamps if (now - stamp) < self._window]
            if active:
                self._attempts[key] = active
            else:
                self._attempts.pop(key, None)
        for key, until in list(self._locked_until.items()):
            if until <= now:
                self._locked_until.pop(key, None)
        for key in list(self._key_order):
            if key not in self._attempts and key not in self._locked_until:
                self._key_order.pop(key, None)
        self._last_cleanup = now

    def retry_after(self, key: str) -> int:
        """Verbleibende Sperrzeit in Sekunden (0 = nicht gesperrt)."""
        if not key:
            return 0
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            until = self._locked_until.get(key, 0.0)
            if until <= now:
                if key in self._locked_until:
                    self._locked_until.pop(key, None)
                    if key not in self._attempts:
                        self._key_order.pop(key, None)
                return 0
            self._touch_key_locked(key)
            return int(until - now) + 1

    def register_failure(self, key: str) -> int:
        """Verbucht einen Fehlversuch; gibt die Sperrzeit zurück (0 = frei)."""
        if not key:
            return 0
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            timestamps = [
                stamp for stamp in self._attempts.get(key, []) if (now - stamp) < self._window
            ]
            timestamps.append(now)
            self._attempts[key] = timestamps
            self._touch_key_locked(key)
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
            self._key_order.pop(key, None)

    def remaining_attempts(self, key: str) -> int:
        if not key:
            return self._max_attempts
        now = time.time()
        with self._lock:
            self._cleanup_locked(now)
            timestamps = [
                stamp for stamp in self._attempts.get(key, []) if (now - stamp) < self._window
            ]
            if timestamps:
                self._attempts[key] = timestamps
            else:
                self._attempts.pop(key, None)
                if key not in self._locked_until:
                    self._key_order.pop(key, None)
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
