"""Authentication policy and request identity services."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from application_services.runtime import (
    import_backend_namespace,
    publish_service,
)

globals().update(import_backend_namespace())


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
    """Expliziter Schutz für öffentlich angebundene Installationen.

    Der Default bleibt für bestehende reine LAN-Installationen kompatibel. Wer
    den Dienst über einen Tunnel veröffentlicht, setzt `APP_REQUIRE_AUTH=1`;
    eine verlorene oder beschädigte Kontokonfiguration öffnet die API dann
    nicht stillschweigend.
    """
    return os.environ.get("APP_REQUIRE_AUTH", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def auth_required() -> bool:
    """Ob Anfragen abgewiesen werden, wenn keine Anmeldung vorliegt.

    Vor abgeschlossener Ersteinrichtung ist die Oberfläche offen – sonst wäre
    der Assistent, der das Konto erst anlegt, selbst nicht erreichbar.
    """
    if fail_closed_auth_enabled():
        return True
    if not appconfig.is_initialized():
        return False
    return auth_configured()


def setup_required() -> bool:
    """Ob die Erst- bzw. Sicherheitsmigration noch abgeschlossen werden muss."""
    return not appconfig.is_initialized() or not auth_configured()


def verify_credentials(username: str, password: str) -> bool:
    """Prüft Zugangsdaten gegen das hinterlegte Konto (zeitkonstant)."""
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
    return appauth.verify_password(str(password or ""), account.get("password_hash", ""))


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
    if not auth_required():
        return True
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
    """Nur explizit aktivieren, wenn der Origin ausschließlich den Tunnel sieht."""
    return os.environ.get("TRUST_CLOUDFLARE_HEADERS", "").strip().casefold() in {
        "1", "true", "yes", "on",
    }


def client_key(request) -> str:
    """Herkunfts-IP für Sperren und Budgets."""
    client = getattr(request, "client", None)
    peer = getattr(client, "host", "") or "unbekannt"
    if not trust_cloudflare_headers_enabled():
        return peer
    raw = str(request.headers.get("cf-connecting-ip", "") or "").strip()
    # CF-Connecting-IP enthält exakt eine Adresse. Listen gehören zu XFF und
    # werden hier absichtlich nicht akzeptiert, damit kein frei wählbarer
    # erster Eintrag zum Umgehen der Login-Sperre wird.
    if not raw or "," in raw or len(raw) > 64:
        return peer
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return peer


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
)
publish_service(globals(), _SERVICE_EXPORTS)
