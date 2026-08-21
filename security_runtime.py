"""Runtime hardening that can be installed without widening server.py.

The project is mid-refactor and still publishes application services back into
its composition root. Keeping these guards in one module lets the security
boundary be tested directly while preserving that transitional architecture.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import stat
import threading
from pathlib import Path
from types import ModuleType
from urllib.parse import quote, urlsplit, urlunsplit


PBKDF2_SECURITY_ITERATIONS = 600_000
SECURE_MIN_PASSWORD_LENGTH = 12
_SECRET_ENV_KEYS = (
    "APP_PASSWORD",
    "JELLYFIN_API_KEY",
    "TMDB_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "SEERR_API_KEY",
    "UI_TRANSLATOR_API_KEY",
    "UPDATE_GITHUB_TOKEN",
    "ROYAL_SETUP_TOKEN",
)
_URL_RE = re.compile(r"https?://[^\s<>'\"]+", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|auth(?:orization)?|password|secret|token)"
    r"\s*([=:])\s*([^\s,;]+)"
)
_install_lock = threading.RLock()
_preinstalled = False
_postinstalled = False
_original_hash_password = None
_original_log_record_factory = None
_remote_browser_context = threading.local()


def _read_secret_file(raw_path: str) -> str:
    raw_path = str(raw_path or "").strip()
    if not raw_path:
        return ""
    path = Path(raw_path).expanduser()
    try:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            return ""
        if file_stat.st_size > 64 * 1024:
            return ""
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError):
        return ""
    return value if value and "\x00" not in value else ""


def load_secret_files_into_environment() -> dict[str, str]:
    """Implement conventional ``NAME_FILE`` support for server-side secrets."""
    loaded: dict[str, str] = {}
    for key in _SECRET_ENV_KEYS:
        if str(os.environ.get(key, "") or ""):
            continue
        value = _read_secret_file(os.environ.get(f"{key}_FILE", ""))
        if value:
            os.environ[key] = value
            loaded[key] = "file"
    return loaded


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,);]}\"":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "[redacted-url]" + trailing
    host = parsed.hostname or ""
    if not host:
        return "[redacted-url]" + trailing
    try:
        port = f":{parsed.port}" if parsed.port is not None else ""
    except ValueError:
        port = ""
    netloc = host
    if ":" in host and not host.startswith("["):
        netloc = f"[{host}]"
    netloc += port
    safe = urlunsplit((parsed.scheme, netloc, parsed.path or "", "", ""))
    return safe + trailing


def redact_security_text(value: object) -> str:
    text = str(value or "")
    text = _URL_RE.sub(_redact_url, text)
    return _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]",
        text,
    )


def install_log_redaction() -> None:
    """Redact URL credentials/query strings and obvious secret assignments."""
    global _original_log_record_factory
    if _original_log_record_factory is not None:
        return
    _original_log_record_factory = logging.getLogRecordFactory()
    original = _original_log_record_factory

    def secure_factory(*args, **kwargs):
        record = original(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:
            return record
        record.msg = redact_security_text(message)
        record.args = ()
        return record

    logging.setLogRecordFactory(secure_factory)


def _install_password_policy(appauth) -> None:
    global _original_hash_password
    if _original_hash_password is None:
        _original_hash_password = appauth.hash_password
    appauth.MIN_PASSWORD_LENGTH = max(
        SECURE_MIN_PASSWORD_LENGTH,
        int(getattr(appauth, "MIN_PASSWORD_LENGTH", 0) or 0),
    )
    appauth.DEFAULT_ITERATIONS = max(
        PBKDF2_SECURITY_ITERATIONS,
        int(getattr(appauth, "DEFAULT_ITERATIONS", 0) or 0),
    )

    def strong_hash_password(password: str, iterations: int | None = None) -> str:
        requested = appauth.DEFAULT_ITERATIONS if iterations is None else int(iterations)
        return _original_hash_password(
            password,
            iterations=max(PBKDF2_SECURITY_ITERATIONS, requested),
        )

    appauth.hash_password = strong_hash_password


def password_hash_needs_upgrade(stored: str) -> bool:
    try:
        scheme, raw_iterations, _salt, _digest = str(stored or "").split("$", 3)
        iterations = int(raw_iterations)
    except (TypeError, ValueError):
        return True
    return scheme != "pbkdf2_sha256" or iterations < PBKDF2_SECURITY_ITERATIONS


def maybe_upgrade_password_hash(appconfig, appauth, account: dict, password: str) -> bool:
    """Rehash a valid legacy settings password after a successful sign-in."""
    if (
        account.get("source") != "settings"
        or not account.get("username")
        or not password_hash_needs_upgrade(account.get("password_hash", ""))
    ):
        return False
    replacement = appauth.hash_password(password)
    return bool(appconfig.save_auth(account["username"], replacement))


class _ChromiumSubprocessProxy:
    """Module-local subprocess proxy that strips Chromium sandbox bypasses."""

    def __init__(self, delegate: ModuleType):
        self._delegate = delegate

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def Popen(self, args, *popen_args, **popen_kwargs):  # noqa: N802 - subprocess API
        normalized = list(args) if isinstance(args, (list, tuple)) else args
        if isinstance(normalized, list):
            is_chromium = any(
                str(part).endswith(("chromium", "google-chrome", "google-chrome-stable"))
                for part in normalized[:1]
            ) or any(str(part).startswith("--remote-debugging-port=") for part in normalized)
            if is_chromium:
                normalized = [part for part in normalized if str(part) != "--no-sandbox"]
                has_debug_port = any(
                    str(part).startswith("--remote-debugging-port=") for part in normalized
                )
                if has_debug_port and not any(
                    str(part) == "--remote-debugging-address=127.0.0.1"
                    for part in normalized
                ):
                    normalized.append("--remote-debugging-address=127.0.0.1")
                for part in normalized:
                    value = str(part)
                    if value.startswith("--user-data-dir="):
                        profile = Path(value.split("=", 1)[1])
                        try:
                            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                            profile.chmod(0o700)
                        except OSError:
                            pass
        return self._delegate.Popen(normalized, *popen_args, **popen_kwargs)


def _remote_browser_base() -> tuple[str, int] | None:
    raw = str(os.environ.get("ROYAL_BROWSER_CDP_URL", "") or "").strip()
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        if parsed.scheme != "http" or not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        port = parsed.port or 9222
    except ValueError:
        return None
    return str(parsed.hostname), int(port)


def _remote_browser_json(path: str, *, method: str = "GET"):
    base = _remote_browser_base()
    if base is None:
        raise RuntimeError("Kein isolierter Royal-Browser konfiguriert.")
    if not (
        path == "/json/list"
        or path.startswith("/json/new?")
        or path.startswith("/json/close/")
        or path == "/json/version"
    ):
        raise ValueError("Nicht erlaubter Chromium-DevTools-Endpunkt.")
    connection = http.client.HTTPConnection(base[0], base[1], timeout=5)
    try:
        connection.request(method, path, headers={"Host": f"{base[0]}:{base[1]}"})
        response = connection.getresponse()
        payload = response.read()
        if response.status != 200:
            raise RuntimeError(f"Isolierter Chromium-Dienst lieferte HTTP {response.status}")
        if not payload:
            return {}
        return json.loads(payload.decode("utf-8"))
    finally:
        connection.close()


def _remote_browser_targets() -> list[dict]:
    payload = _remote_browser_json("/json/list")
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _rewrite_remote_websocket_url(value: str) -> str:
    base = _remote_browser_base()
    if base is None:
        raise RuntimeError("Kein isolierter Royal-Browser konfiguriert.")
    try:
        parsed = urlsplit(str(value or ""))
    except ValueError as exc:
        raise RuntimeError("Ungültige Chromium-WebSocket-Adresse.") from exc
    if parsed.scheme not in {"ws", "wss"} or not parsed.path.startswith("/devtools/"):
        raise RuntimeError("Ungültige Chromium-WebSocket-Adresse.")
    return urlunsplit(("ws", f"{base[0]}:{base[1]}", parsed.path, parsed.query, ""))


def _remote_new_target() -> tuple[dict, set[str]]:
    before = {
        str(item.get("id") or "")
        for item in _remote_browser_targets()
        if item.get("id")
    }
    target = _remote_browser_json(
        "/json/new?" + quote("about:blank", safe=""),
        method="PUT",
    )
    if not isinstance(target, dict) or not target.get("id") or not target.get("webSocketDebuggerUrl"):
        raise RuntimeError("Isolierter Chromium-Dienst konnte keinen Tab anlegen.")
    return target, before


def _remote_close_target(target_id: str) -> None:
    target_id = str(target_id or "").strip()
    if not target_id or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id):
        return
    try:
        _remote_browser_json(f"/json/close/{target_id}")
    except Exception:
        pass


class _RemoteProcess:
    """Popen-compatible lifecycle seam for one tab in the isolated browser."""

    def __init__(self, target_id: str):
        self.target_id = target_id
        self._closed = False

    def poll(self):
        return 0 if self._closed else None

    def terminate(self):
        if not self._closed:
            _remote_close_target(self.target_id)
            self._closed = True

    def wait(self, timeout=None):
        del timeout
        self.terminate()
        return 0

    def kill(self):
        self.terminate()


def _configure_verification_cdp(module, cdp) -> None:
    cdp._command("Network.enable")
    cdp._command("Page.enable")
    cdp._command("Runtime.enable")
    cdp._command("Emulation.setDeviceMetricsOverride", {
        "width": module.VIEWPORT_WIDTH,
        "height": module.VIEWPORT_HEIGHT,
        "deviceScaleFactor": 1,
        "mobile": False,
    })
    cdp._command("Network.setUserAgentOverride", {
        "userAgent": module.CHROME_USER_AGENT,
        "acceptLanguage": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "platform": "Win32",
    })


def _configure_shared_cdp(module, cdp) -> None:
    cdp.command("Network.enable")
    cdp.command("Page.enable")
    cdp.command("Runtime.enable")
    cdp.command("Emulation.setDeviceMetricsOverride", {
        "width": module.VIEWPORT_WIDTH,
        "height": module.VIEWPORT_HEIGHT,
        "deviceScaleFactor": 1,
        "mobile": False,
    })
    cdp.command("Network.setUserAgentOverride", {
        "userAgent": module.SERIESSTREAM_USER_AGENT,
        "acceptLanguage": module.SERIESSTREAM_ACCEPT_LANGUAGE,
        "platform": "Win32",
    })


def _install_remote_browser_adapters() -> bool:
    if _remote_browser_base() is None:
        return False
    import serienstream_shared_session as shared
    import serienstream_verification as verification

    if not getattr(verification.SerienStreamVerificationManager, "_royal_remote_browser", False):
        def verification_start_processes(self):
            target, _before = _remote_new_target()
            cdp = verification._Cdp(
                _rewrite_remote_websocket_url(str(target["webSocketDebuggerUrl"]))
            )
            _configure_verification_cdp(verification, cdp)
            self._chrome = _RemoteProcess(str(target["id"]))
            self._xvfb = None
            self._port = 0
            self._display = "isolated-browser"
            return cdp

        verification.SerienStreamVerificationManager._start_processes_locked = verification_start_processes
        verification.SerienStreamVerificationManager._royal_remote_browser = True

    if not getattr(shared._BrowserRuntime, "_royal_remote_browser", False):
        def shared_start(self):
            target, before = _remote_new_target()
            self._royal_remote_before = before
            self._royal_remote_target_id = str(target["id"])
            cdp = shared._Cdp(
                _rewrite_remote_websocket_url(str(target["webSocketDebuggerUrl"]))
            )
            _configure_shared_cdp(shared, cdp)
            self.chrome = _RemoteProcess(self._royal_remote_target_id)
            self.xvfb = None
            self.port = 0
            self.display = "isolated-browser"
            self.cdp = cdp
            _remote_browser_context.shared_runtime = self
            return cdp

        shared._BrowserRuntime.start = shared_start
        shared._BrowserRuntime._royal_remote_browser = True

        def remote_external_target(_port: int) -> str:
            runtime = getattr(_remote_browser_context, "shared_runtime", None)
            before = set(getattr(runtime, "_royal_remote_before", set()) or set())
            own_id = str(getattr(runtime, "_royal_remote_target_id", "") or "")
            try:
                for target in _remote_browser_targets():
                    target_id = str(target.get("id") or "")
                    if not target_id or target_id == own_id or target_id in before:
                        continue
                    external = shared._external_http_url(str(target.get("url") or ""))
                    if external:
                        return external
            except Exception:
                return ""
            return ""

        shared._external_target = remote_external_target
    return True


def _install_browser_sandbox_guards() -> None:
    """Use an isolated NAS browser; otherwise enforce Chromium's native sandbox."""
    if _install_remote_browser_adapters():
        return
    for module_name in ("serienstream_verification", "serienstream_shared_session"):
        try:
            module = __import__(module_name)
        except Exception:
            continue
        current = getattr(module, "subprocess", None)
        if current is None or isinstance(current, _ChromiumSubprocessProxy):
            continue
        module.subprocess = _ChromiumSubprocessProxy(current)


def _secure_cookie_load(self) -> dict:
    path = Path(self._cookie_file)
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        clean: dict[str, str] = {}
        for name, value in list(payload.items())[:256]:
            name = str(name or "")
            value = str(value or "")
            if name and len(name) <= 256 and len(value) <= 16_384:
                clean[name] = value
        try:
            path.chmod(0o600)
        except OSError:
            pass
        logging.getLogger("session_manager").info(
            "[%s] Cookies geladen: %d Einträge",
            self.TARGET_DOMAIN,
            len(clean),
        )
        return clean
    except (OSError, ValueError, TypeError, UnicodeError):
        return {}


def _secure_cookie_save(self) -> None:
    path = Path(self._cookie_file)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(self._cookies), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        logging.getLogger("session_manager").warning(
            "Cookie-Speicherung fehlgeschlagen: %s",
            exc,
        )


def _install_cookie_persistence_hardening() -> None:
    try:
        import session_manager
    except Exception:
        return
    cls = session_manager.SessionManager
    if getattr(cls, "_royal_secure_cookie_io", False):
        return
    cls._load_cookies = _secure_cookie_load
    cls._save_cookies = _secure_cookie_save
    cls._royal_secure_cookie_io = True


def install_pre_state_security(appconfig, appauth) -> None:
    """Install guards before ``AppState`` reads credentials/integrations."""
    global _preinstalled
    with _install_lock:
        if _preinstalled:
            return
        load_secret_files_into_environment()
        install_log_redaction()
        _install_password_policy(appauth)
        _install_cookie_persistence_hardening()
        _install_browser_sandbox_guards()
        _preinstalled = True


def _harden_path_permissions(path: Path, mode: int) -> None:
    try:
        if path.is_symlink() or not path.exists():
            return
        path.chmod(mode)
    except OSError:
        pass


def _install_update_checker_hardening(update_checker_module) -> None:
    cls = update_checker_module.UpdateChecker
    if getattr(cls, "_royal_security_hardened", False):
        return

    def quality_gate_state(self, commit: str) -> str:
        payload = self._get_json(
            f"commits/{update_checker_module.quote(commit, safe='')}/check-runs?per_page=100",
        )
        runs = [
            item for item in payload.get("check_runs", [])
            if isinstance(item, dict) and item.get("name") == "verify"
        ]
        if any(
            item.get("status") == "completed" and item.get("conclusion") == "success"
            for item in runs
        ):
            return "passed"
        if any(item.get("status") != "completed" for item in runs):
            return "pending"
        return "failed" if runs else "missing"

    original_check_uncached = cls._check_uncached

    def check_uncached(self):
        payload = original_check_uncached(self)
        latest_sha = str(payload.get("latest_sha") or "")
        if not latest_sha:
            payload.setdefault("commit_signature_verified", False)
            payload.setdefault("security_approved", False)
            return payload
        verified = False
        reason = "missing"
        try:
            commit_payload = self._get_json(
                f"commits/{update_checker_module.quote(latest_sha, safe='')}",
            )
            verification = ((commit_payload.get("commit") or {}).get("verification") or {})
            verified = bool(verification.get("verified"))
            reason = str(verification.get("reason") or ("valid" if verified else "unverified"))
        except Exception as exc:  # fail closed on trust metadata errors
            reason = f"verification_error:{type(exc).__name__}"
        quality_passed = payload.get("quality_gate") == "passed"
        security_approved = bool(verified and quality_passed)
        payload.update({
            "commit_signature_verified": verified,
            "commit_signature_reason": reason,
            "security_approved": security_approved,
        })
        if not security_approved:
            payload["update_available"] = False
            payload["security_blocked"] = True
        return payload

    cls._quality_gate_state = quality_gate_state
    cls._check_uncached = check_uncached
    cls._royal_security_hardened = True


def install_post_state_security(backend) -> None:
    """Apply guards that need the fully assembled composition root."""
    global _postinstalled
    with _install_lock:
        if _postinstalled:
            return
        try:
            import update_checker
            _install_update_checker_hardening(update_checker)
            checker = getattr(backend, "UPDATE_CHECKER", None)
            if checker is not None:
                checker._cache = None
                checker._cache_time = 0.0
        except Exception:
            logging.getLogger(__name__).exception(
                "Updater-Sicherheitsregeln konnten nicht aktiviert werden"
            )

        try:
            config_path = Path(backend.appconfig.config_path())
            _harden_path_permissions(config_path, 0o600)
            _harden_path_permissions(Path(backend.appconfig.sessions_file()), 0o600)
            data_root = config_path.parent.parent
            for cookie in data_root.glob(".cf_cookies_*.json"):
                _harden_path_permissions(cookie, 0o600)
            _harden_path_permissions(data_root / "serienstream-browser-profile", 0o700)
        except Exception:
            pass
        _postinstalled = True
