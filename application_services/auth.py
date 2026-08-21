"""Authentication policy and request identity services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)
from proxy_security import client_ip as secure_client_ip
from proxy_security import request_is_secure as trusted_request_is_secure
from security_runtime import install_pre_state_security, maybe_upgrade_password_hash


globals().update(import_backend_namespace())

# This service is imported before AppState is constructed.  Security-sensitive
# environment/secret loading and password policy therefore take effect before
# integrations or credentials are read into runtime state.
install_pre_state_security(appconfig, appauth)


# ---------------------------------------------------------------------------
# Anmeldung
#
# Es gibt genau EIN Administratorkonto; die App ist durchgehend auf einen
# Nutzer ausgelegt (eine Watchlist, eine Queue, ein Jellyfin-Benutzer).
# Die Weboberfläche nutzt ein Sitzungs-Cookie. Native Clients können dasselbe
# widerrufbare, serverseitig gehashte Sitzungsformat als Bearer-Token verwenden.
# HTTP-Basic bleibt für bestehende Skripte und Health-Checks zusätzlich gültig.
# ---------------------------------------------------------------------------
def auth_account() -> dict:
    """Aktuell hinterlegtes Konto (settings.ini oder APP_USERNAME/APP_PASSWORD)."""
    return appconfig.load_auth()


def auth_configured() -> bool:
    return bool(auth_account().get("configured"))


def fail_closed_auth_enabled() -> bool:
    """Royal besitzt nach dem Security-Hardening keine offene API-Betriebsart.

    First-run setup is the only unauthenticated administration surface and is
    protected by its one-time bootstrap token. ``APP_REQUIRE_AUTH`` remains a
    compatibility setting but can no longer turn an initialized instance into
    an unauthenticated service when account state is missing or damaged.
    """
    return True


def auth_required() -> bool:
    """All non-public application APIs require an authenticated session."""
    return True


def setup_required() -> bool:
    """Ob die Erst- bzw. Sicherheitsmigration noch abgeschlossen werden muss."""
    return not appconfig.is_initialized() or not auth_configured()


def verify_credentials(username: str, password: str) -> bool:
    """Prüft Zugangsdaten zeitkonstant und aktualisiert alte Hashparameter."""
    account = auth_account()
    if not account.get("configured"):
        return False
    if not secrets.compare_digest(str(username or ""), str(account.get("username", ""))):
        # Trotzdem eine Hash-Runde rechnen, damit ein falscher Benutzername
        # nicht spürbar schneller beantwortet wird als ein falsches Passwort.
        appauth.verify_password(str(password or ""), account.get("password_hash", ""))
        return False
    if account.get("source") == "env":
        return secrets.compare_digest(str(password or ""), str(account.get("env_password", "")))
    verified = appauth.verify_password(str(password or ""), account.get("password_hash", ""))
    if verified:
        try:
            maybe_upgrade_password_hash(appconfig, appauth, account, str(password or ""))
        except Exception as exc:  # login stays available if a background rehash cannot persist
            log(f"Passwort-Hash konnte nicht automatisch aktualisiert werden: {exc}", "warn")
    return verified


def _authorized_basic_header(value: str, guard_key: str = "") -> bool:
    """Erlaubt weiterhin `Authorization: Basic` für Skripte und Monitoring."""
    if not value or not value.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(value[6:], validate=True).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        return False
    key = guard_key or "basic-global"
    if BASIC_AUTH_GUARD.retry_after(key):
        return False
    authenticated = verify_credentials(username, password)
    if authenticated:
        BASIC_AUTH_GUARD.register_success(key)
    else:
        BASIC_AUTH_GUARD.register_failure(key)
    return authenticated


def _bearer_token(headers) -> str:
    """Liest ein Bearer-Token, ohne es zu protokollieren oder umzuschreiben."""
    value = str(headers.get("authorization", "") or "").strip()
    scheme, separator, credential = value.partition(" ")
    if not separator or scheme.casefold() != "bearer":
        return ""
    token = credential.strip()
    if not token or any(char.isspace() for char in token):
        return ""
    return token


def _session_token(scope_cookies: dict) -> str:
    return str(scope_cookies.get(appauth.SESSION_COOKIE_NAME) or "")


def authenticated_mobile_token(headers, *, touch: bool = True) -> str:
    """Gibt ausschließlich ein gültiges Mobile-Bearer-Token zurück."""
    bearer = _bearer_token(headers)
    if bearer and SESSION_STORE.validate(
        bearer, appauth.SESSION_KIND_MOBILE, touch=touch,
    ):
        return bearer
    return ""


def authenticated_web_token(cookies, *, touch: bool = True) -> str:
    """Gibt ausschließlich ein gültiges Browser-Cookie-Token zurück."""
    cookie = _session_token(cookies)
    if cookie and SESSION_STORE.validate(
        cookie, appauth.SESSION_KIND_WEB, touch=touch,
    ):
        return cookie
    return ""


def request_auth_method(
    headers,
    cookies,
    guard_key: str = "",
    *,
    versioned: bool = False,
    allow_mobile_bearer: bool = True,
    allow_basic: bool = True,
    touch: bool = True,
) -> str:
    """Authentifizierungsweg für Statusantworten; enthält nie Zugangsdaten."""
    if allow_mobile_bearer and authenticated_mobile_token(headers, touch=touch):
        return "bearer"
    if not versioned and authenticated_web_token(cookies, touch=touch):
        return "cookie"
    if (
        not versioned
        and allow_basic
        and _authorized_basic_header(headers.get("authorization", ""), guard_key)
    ):
        return "basic"
    return "none"


def request_is_authenticated(
    headers,
    cookies,
    guard_key: str = "",
    *,
    versioned: bool = False,
    allow_mobile_bearer: bool = True,
    allow_basic: bool = True,
    touch: bool = True,
) -> bool:
    """Gültiges Cookie-/Bearer-Token oder gültiger Basic-Header?"""
    if allow_mobile_bearer and authenticated_mobile_token(headers, touch=touch):
        return True
    if not versioned and authenticated_web_token(cookies, touch=touch):
        return True
    return bool(
        not versioned
        and allow_basic
        and _authorized_basic_header(headers.get("authorization", ""), guard_key)
    )


def trust_cloudflare_headers_enabled() -> bool:
    """Compatibility flag; peer trust is enforced separately by proxy_security."""
    return os.environ.get("TRUST_CLOUDFLARE_HEADERS", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def client_key(request) -> str:
    """Spoof-resistant Herkunfts-IP für Sperren und Budgets."""
    return secure_client_ip(request)


def _request_is_secure(request) -> bool:
    """HTTPS only follows forwarding metadata from an explicitly trusted proxy."""
    return trusted_request_is_secure(request)


def _set_session_cookie(response, request, token: str) -> None:
    response.set_cookie(
        appauth.SESSION_COOKIE_NAME,
        token,
        max_age=appauth.DEFAULT_SESSION_TTL_SECONDS,
        httponly=True,
        samesite="strict",
        secure=_request_is_secure(request),
        path="/",
    )


_SERVICE_EXPORTS = (
    "auth_account",
    "auth_configured",
    "fail_closed_auth_enabled",
    "auth_required",
    "setup_required",
    "verify_credentials",
    "_authorized_basic_header",
    "_bearer_token",
    "_session_token",
    "authenticated_mobile_token",
    "authenticated_web_token",
    "request_auth_method",
    "request_is_authenticated",
    "trust_cloudflare_headers_enabled",
    "client_key",
    "_request_is_secure",
    "_set_session_cookie",
)
publish_service(globals(), _SERVICE_EXPORTS)
