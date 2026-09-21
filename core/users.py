"""Persistent household accounts with a one-time legacy-admin migration."""

from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path

from core.auth import normalize_username, validate_username

ADMIN, MEMBER = "admin", "member"


class UserStore:
    def __init__(self, path: Path, legacy_account: dict) -> None:
        self._path, self._lock, self._users = Path(path), threading.RLock(), {}
        self._load()
        if not self._users and legacy_account.get("configured"):
            self._migrate_legacy(legacy_account)

    def _load(self) -> None:
        try: raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError): return
        migrated = False
        for item in raw.get("users", []) if isinstance(raw, dict) else []:
            if not isinstance(item, dict) or not item.get("id") or not item.get("username"): continue
            stored = dict(item)
            is_legacy_admin = str(stored["id"]) == "admin-legacy"
            if "taste_onboarding_required" not in stored or "taste_onboarding_completed_at" not in stored:
                migrated = True
            stored.setdefault("taste_onboarding_required", not is_legacy_admin)
            stored.setdefault(
                "taste_onboarding_completed_at",
                float(stored.get("updated_at") or 0) if is_legacy_admin else 0.0,
            )
            self._users[str(stored["id"])] = stored
        if migrated:
            self._save()

    def _save(self) -> None:
        payload = {"version": 1, "users": list(self._users.values())}
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, self._path)
        try: self._path.chmod(0o600)
        except OSError: pass

    def _migrate_legacy(self, account: dict) -> None:
        username = validate_username(account["username"])
        self._users["admin-legacy"] = {"id": "admin-legacy", "username": username, "display_name": username, "password_hash": account.get("password_hash", ""), "env_password": account.get("env_password", ""), "source": account.get("source", "settings"), "role": ADMIN, "enabled": True, "setup_required": False, "taste_onboarding_required": False, "taste_onboarding_completed_at": time.time(), "created_at": time.time(), "updated_at": time.time()}
        self._save()

    def ensure_legacy(self, account: dict) -> None:
        """Migrate an account created after process startup (first-run setup)."""
        with self._lock:
            if not self._users and account.get("configured"):
                self._migrate_legacy(account)

    def find(self, username: str) -> dict | None:
        key = normalize_username(username).casefold()
        with self._lock:
            for item in self._users.values():
                if str(item.get("username", "")).casefold() == key: return dict(item)
        return None

    def get(self, user_id: str) -> dict | None:
        with self._lock:
            item = self._users.get(str(user_id)); return dict(item) if item else None

    def public(self, user: dict) -> dict:
        return {key: user.get(key) for key in ("id", "username", "display_name", "role", "enabled", "setup_required", "taste_onboarding_required", "taste_onboarding_completed_at", "created_at", "updated_at")}

    def list(self) -> list[dict]:
        with self._lock: return [self.public(item) for item in self._users.values()]

    def create(self, display_name: str, username: str, role: str) -> dict:
        username = validate_username(username)
        if role not in {ADMIN, MEMBER}: raise ValueError("Ungültige Rolle.")
        if not str(display_name).strip(): raise ValueError("Anzeigename fehlt.")
        with self._lock:
            if self.find(username): raise ValueError("Benutzername ist bereits vergeben.")
            now, user_id = time.time(), secrets.token_urlsafe(12)
            user = {"id": user_id, "username": username, "display_name": str(display_name).strip()[:120], "password_hash": "", "role": role, "enabled": True, "setup_required": True, "taste_onboarding_required": True, "taste_onboarding_completed_at": 0.0, "created_at": now, "updated_at": now}
            self._users[user_id] = user; self._save(); return self.public(user)

    def set_password(self, user_id: str, password_hash: str) -> dict:
        with self._lock:
            user = self._users.get(user_id)
            if not user: raise ValueError("Benutzer nicht gefunden.")
            user.update(password_hash=password_hash, env_password="", source="settings", setup_required=False, updated_at=time.time()); self._save(); return self.public(user)

    def reset_password(self, user_id: str) -> dict:
        with self._lock:
            user = self._users.get(user_id)
            if not user: raise ValueError("Benutzer nicht gefunden.")
            user.update(password_hash="", env_password="", setup_required=True, updated_at=time.time()); self._save(); return self.public(user)

    def complete_taste_onboarding(self, user_id: str) -> dict:
        with self._lock:
            user = self._users.get(user_id)
            if not user: raise ValueError("Benutzer nicht gefunden.")
            user.update(taste_onboarding_required=False, taste_onboarding_completed_at=time.time(), updated_at=time.time())
            self._save()
            return self.public(user)

    def require_taste_onboarding(self, user_id: str) -> dict:
        with self._lock:
            user = self._users.get(user_id)
            if not user: raise ValueError("Benutzer nicht gefunden.")
            user.update(taste_onboarding_required=True, taste_onboarding_completed_at=0.0, updated_at=time.time())
            self._save()
            return self.public(user)

    def set_enabled(self, user_id: str, enabled: bool) -> dict:
        with self._lock:
            user = self._users.get(user_id)
            if not user: raise ValueError("Benutzer nicht gefunden.")
            if not enabled and user.get("role") == ADMIN and sum(bool(x.get("enabled")) and x.get("role") == ADMIN for x in self._users.values()) <= 1: raise ValueError("Der letzte aktive Administrator kann nicht deaktiviert werden.")
            user.update(enabled=bool(enabled), updated_at=time.time()); self._save(); return self.public(user)
