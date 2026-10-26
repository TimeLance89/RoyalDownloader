"""RFC 6238 TOTP with encrypted seeds, replay protection and one-use recovery."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

from core.auth import LoginGuard


class TotpError(ValueError):
    def __init__(self, code, message, status=400, retry_after=0):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


def totp(secret, counter, digits=6):
    key = base64.b32decode(secret, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff
    return str(value % (10 ** digits)).zfill(digits)


class TotpService:
    def __init__(self, users, clock=time.time):
        self.users, self.clock = users, clock
        self.lock = users._lock
        self.key_path = users._path.with_name("mfa.key")
        self.guard = LoginGuard(max_attempts=5, window_seconds=300, lockout_seconds=300)

    def _cipher(self, *, create=False):
        try:
            if create and not self.key_path.exists():
                if any(user.get("mfa", {}).get("enabled") for user in self.users._users.values()):
                    raise OSError("missing key for active MFA")
                self.key_path.parent.mkdir(parents=True, exist_ok=True)
                descriptor = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(Fernet.generate_key()); handle.flush(); os.fsync(handle.fileno())
            if self.key_path.is_symlink():
                raise OSError("invalid key file")
            return Fernet(self.key_path.read_bytes())
        except (OSError, ValueError) as exc:
            raise TotpError("mfa_unavailable", "2FA-Schlüssel nicht verfügbar. Sicherung von users.json und mfa.key prüfen.", 503) from exc

    def _decrypt(self, value):
        try:
            return self._cipher().decrypt(value.encode()).decode()
        except (InvalidToken, UnicodeError, AttributeError) as exc:
            raise TotpError("mfa_unavailable", "2FA-Daten konnten nicht entschlüsselt werden.", 503) from exc

    def enabled(self, user_id):
        return bool(self.users.mfa_state(user_id).get("enabled"))

    def _save(self, user_id, state):
        try:
            self.users.set_mfa_state(user_id, state)
        except OSError as exc:
            raise TotpError("mfa_store_unavailable", "2FA-Änderung konnte nicht sicher gespeichert werden. Bitte später erneut versuchen.", 503) from exc

    def status(self, user_id):
        state = self.users.mfa_state(user_id)
        return {"enabled": bool(state.get("enabled")), "recovery_codes_remaining": len(state.get("recovery", [])),
                "pending": bool(state.get("pending") and state.get("expires_at", 0) > self.clock())}

    def begin(self, user_id, username):
        with self.lock:
            state = self.users.mfa_state(user_id)
            if state.get("enabled"):
                raise TotpError("mfa_already_enabled", "2FA ist bereits aktiv. Zum Wechsel zuerst mit Passwort und Code deaktivieren.", 409)
            secret = base64.b32encode(secrets.token_bytes(20)).decode()
            encrypted = self._cipher(create=True).encrypt(secret.encode()).decode()
            self._save(user_id, {"enabled": False, "pending": encrypted, "expires_at": self.clock() + 600})
            uri = "otpauth://totp/" + quote("RoyalDownloader:" + username, safe="") + "?" + urlencode({
                "secret": secret, "issuer": "RoyalDownloader", "algorithm": "SHA1", "digits": 6, "period": 30})
            return {"secret": secret, "otpauth_uri": uri, "expires_in": 600}

    def _budget(self, user_id):
        retry = self.guard.retry_after(user_id)
        if retry:
            raise TotpError("mfa_rate_limited", "Zu viele falsche Codes. Bitte später erneut versuchen.", 429, retry)

    def _invalid(self, user_id):
        retry = self.guard.register_failure(user_id)
        raise TotpError("mfa_invalid", "Code ungültig, abgelaufen oder bereits verwendet. Nächsten Code oder Wiederherstellungscode verwenden.", 429 if retry else 403, retry)

    def _counter(self, secret, code, previous=-1):
        if not re.fullmatch(r"[0-9]{6}", code):
            return None
        now = int(self.clock() // 30)
        # Accept one adjacent time step for small phone/server clock drift.
        return next((counter for counter in (now, now - 1, now + 1) if counter >= 0 and counter > previous
                     and hmac.compare_digest(totp(secret, counter), code)), None)

    @staticmethod
    def _recovery_codes():
        codes = [secrets.token_hex(12) for _ in range(10)]
        return ["-".join(code[i:i + 6] for i in range(0, 24, 6)) for code in codes]

    @staticmethod
    def _hash(code):
        return hashlib.sha256(code.replace("-", "").replace(" ", "").casefold().encode()).hexdigest()

    def confirm(self, user_id, code):
        with self.lock:
            self._budget(user_id)
            state = self.users.mfa_state(user_id)
            if state.get("enabled") or not state.get("pending") or state.get("expires_at", 0) <= self.clock():
                raise TotpError("mfa_setup_expired", "Einrichtung abgelaufen. Bitte neu beginnen.", 409)
            counter = self._counter(self._decrypt(state["pending"]), code.strip())
            if counter is None:
                self._invalid(user_id)
            codes = self._recovery_codes()
            self._save(user_id, {"enabled": True, "secret": state["pending"], "counter": counter,
                                              "epoch": secrets.token_hex(16),
                                              "recovery": [self._hash(value) for value in codes]})
            self.guard.register_success(user_id)
            return codes

    def verify(self, user_id, code):
        with self.lock:
            state = self.users.mfa_state(user_id)
            if not state.get("enabled"):
                return ""
            if not code:
                raise TotpError("mfa_required", "Authenticator-Code oder Wiederherstellungscode erforderlich.", 403)
            self._budget(user_id)
            code = code.strip()
            digest = self._hash(code)
            recovery = next((value for value in state.get("recovery", []) if hmac.compare_digest(value, digest)), None)
            counter = None if recovery else self._counter(self._decrypt(state.get("secret")), code, state.get("counter", -1))
            if counter is None and recovery is None:
                self._invalid(user_id)
            if recovery:
                state["recovery"].remove(recovery)
            else:
                state["counter"] = counter
            self._save(user_id, state)
            self.guard.register_success(user_id)
            return state["epoch"]

    def disable(self, user_id, code):
        with self.lock:
            self.verify(user_id, code)
            self._save(user_id, {})

    def regenerate(self, user_id, code):
        with self.lock:
            if not self.enabled(user_id):
                raise TotpError("mfa_not_enabled", "2FA ist nicht aktiv.", 409)
            self.verify(user_id, code)
            state = self.users.mfa_state(user_id)
            codes = self._recovery_codes()
            state["recovery"] = [self._hash(value) for value in codes]
            self._save(user_id, state)
            return codes
