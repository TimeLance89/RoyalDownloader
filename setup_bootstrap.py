"""One-time first-run bootstrap token for claiming a Royal installation.

The setup API is intentionally reachable before an administrator account exists.
A high-entropy bootstrap secret therefore protects the *first* account creation
from another device on the LAN.  The generated secret is stored mode 0600 and
announced in the server/container log, never returned by the HTTP API.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

import config as appconfig
from proxy_security import client_ip

logger = logging.getLogger(__name__)

TOKEN_MIN_LENGTH = 16
TOKEN_MAX_LENGTH = 256
MAX_FAILURES = 5
ATTEMPT_WINDOW_SECONDS = 5 * 60
LOCKOUT_SECONDS = 5 * 60

_lock = threading.RLock()
_cached_token = ""
_announced_token = ""
_attempts: dict[str, list[float]] = {}
_locked_until: dict[str, float] = {}


class SetupBootstrapError(ValueError):
    pass


class SetupBootstrapLocked(SetupBootstrapError):
    def __init__(self, retry_after: int):
        self.retry_after = max(1, int(retry_after))
        super().__init__(f"Zu viele ungültige Setup-Codes. Bitte {self.retry_after} Sekunden warten.")


def _token_file() -> Path:
    return appconfig.sessions_file().with_name("setup_bootstrap.json")


def _read_secret_file(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    path = Path(raw).expanduser()
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 64 * 1024:
            return ""
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        return ""
    return value if TOKEN_MIN_LENGTH <= len(value) <= TOKEN_MAX_LENGTH else ""


def _configured_token() -> str:
    direct = str(os.environ.get("ROYAL_SETUP_TOKEN", "") or "").strip()
    if TOKEN_MIN_LENGTH <= len(direct) <= TOKEN_MAX_LENGTH:
        return direct
    return _read_secret_file(os.environ.get("ROYAL_SETUP_TOKEN_FILE", ""))


def _load_persisted_token() -> str:
    path = _token_file()
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
            return ""
        payload = json.loads(path.read_text(encoding="utf-8"))
        token = str(payload.get("token") or "") if isinstance(payload, dict) else ""
        if TOKEN_MIN_LENGTH <= len(token) <= TOKEN_MAX_LENGTH:
            try:
                path.chmod(0o600)
            except OSError:
                pass
            return token
    except (OSError, ValueError, TypeError, UnicodeError):
        return ""
    return ""


def _write_persisted_token(token: str) -> None:
    path = _token_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    payload = json.dumps({"version": 1, "token": token, "created_at": int(time.time())}) + "\n"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def ensure_setup_token() -> str:
    global _cached_token, _announced_token
    with _lock:
        token = _configured_token() or _cached_token or _load_persisted_token()
        if not token:
            token = "RD-" + secrets.token_urlsafe(24)
            _write_persisted_token(token)
        _cached_token = token
        if _announced_token != token:
            logger.warning(
                "ROYAL ERSTEINRICHTUNG – Sicherheitscode: %s  "
                "(nur für die erste Kontoübernahme; niemals an Fremde weitergeben)",
                token,
            )
            _announced_token = token
        return token


def bootstrap_status() -> dict:
    ensure_setup_token()
    return {
        "bootstrap_required": True,
        "bootstrap_hint": (
            "Den einmaligen Sicherheitscode aus dem Royal-Server-/Container-Log eingeben."
        ),
    }


def _guard_key(request) -> str:
    return client_ip(request) or "unbekannt"


def _retry_after_locked(key: str, now: float) -> int:
    until = float(_locked_until.get(key) or 0)
    if until <= now:
        _locked_until.pop(key, None)
        return 0
    return max(1, int(until - now + 0.999))


def _record_failure_locked(key: str, now: float) -> int:
    cutoff = now - ATTEMPT_WINDOW_SECONDS
    failures = [stamp for stamp in _attempts.get(key, []) if stamp >= cutoff]
    failures.append(now)
    _attempts[key] = failures
    if len(failures) >= MAX_FAILURES:
        _attempts.pop(key, None)
        _locked_until[key] = now + LOCKOUT_SECONDS
        return int(LOCKOUT_SECONDS)
    return 0


def verify_setup_token(candidate: str, request) -> None:
    expected = ensure_setup_token()
    supplied = str(candidate or "").strip()
    key = _guard_key(request)
    now = time.monotonic()
    with _lock:
        retry = _retry_after_locked(key, now)
        if retry:
            raise SetupBootstrapLocked(retry)
        valid = bool(
            TOKEN_MIN_LENGTH <= len(supplied) <= TOKEN_MAX_LENGTH
            and hmac.compare_digest(supplied, expected)
        )
        if not valid:
            lockout = _record_failure_locked(key, now)
            if lockout:
                raise SetupBootstrapLocked(lockout)
            remaining = max(0, MAX_FAILURES - len(_attempts.get(key, [])))
            raise SetupBootstrapError(
                f"Der Setup-Sicherheitscode ist ungültig. Noch {remaining} Versuch(e)."
            )
        _attempts.pop(key, None)
        _locked_until.pop(key, None)


def consume_setup_token() -> None:
    """Invalidate generated first-run state after setup completed successfully."""
    global _cached_token, _announced_token
    with _lock:
        _cached_token = ""
        _announced_token = ""
        _attempts.clear()
        _locked_until.clear()
        try:
            _token_file().unlink(missing_ok=True)
        except OSError:
            pass
