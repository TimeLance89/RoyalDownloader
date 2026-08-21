"""Architecture contract for the staged application-service migration."""

from __future__ import annotations

import base64
from pathlib import Path
from types import SimpleNamespace

from application_services.auth import (
    AuthRuntimeDependencies,
    configure_auth_dependencies,
)
import application_services.auth as auth_service
from application_services.security_hardening import (
    SecurityHardeningDependencies,
    install_security_hardening,
)


ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "application_services"
LEGACY_NAMESPACE_PATTERN = "globals().update(import_backend_namespace())"
LEGACY_RUNTIME_NAMESPACE_ALLOWLIST = frozenset(
    {
        "automation.py",
        "content_language_policy.py",
        "download_lifecycle.py",
        "download_queue.py",
        "media_clients.py",
        "media_identity.py",
        "movie_catalog.py",
        "movie_fallback_policy.py",
        "movie_search_availability.py",
        "movie_subscription_commit_guard.py",
        "movie_subscription_delivery_guard.py",
        "movie_subscription_quality.py",
        "movie_subscription_repeat_guard.py",
        "movie_subscription_runtime_hardening.py",
        "movie_subscription_stream_quality.py",
        "persistence.py",
        "seerr.py",
        "series_catalog.py",
        "series_catalog_cache.py",
        "smart_automation.py",
        "source_resolution.py",
        "telegram_commands.py",
        "telegram_requests.py",
        "trailer_policy.py",
        "updater.py",
    }
)
MIGRATED_SERVICES = frozenset({"auth.py", "security_hardening.py"})


def _legacy_namespace_users() -> set[str]:
    return {
        path.name
        for path in SERVICES.glob("*.py")
        if LEGACY_NAMESPACE_PATTERN in path.read_text(encoding="utf-8")
    }


def test_legacy_runtime_namespace_allowlist_is_exact_and_cannot_grow():
    actual = _legacy_namespace_users()
    assert actual == LEGACY_RUNTIME_NAMESPACE_ALLOWLIST, (
        "Application-service runtime namespace debt changed. New modules may "
        "not use globals().update(import_backend_namespace()); migrate them to "
        "explicit dependencies instead. If a legacy module was migrated, "
        "shrink the allowlist. "
        f"added={sorted(actual - LEGACY_RUNTIME_NAMESPACE_ALLOWLIST)}, "
        f"removed={sorted(LEGACY_RUNTIME_NAMESPACE_ALLOWLIST - actual)}"
    )


def test_migrated_services_have_no_implicit_namespace_or_f821_suppression():
    for name in MIGRATED_SERVICES:
        source = (SERVICES / name).read_text(encoding="utf-8")
        assert LEGACY_NAMESPACE_PATTERN not in source
        assert "import_backend_namespace" not in source
        assert "ruff: noqa: F821" not in source


class _FakeGuard:
    def __init__(self, *, blocked: bool = False):
        self.blocked = blocked
        self.successes: list[str] = []
        self.failures: list[str] = []

    def retry_after(self, _key: str) -> int:
        return 10 if self.blocked else 0

    def register_success(self, key: str) -> None:
        self.successes.append(key)

    def register_failure(self, key: str) -> None:
        self.failures.append(key)


class _FakeSessionStore:
    def __init__(self):
        self.calls: list[tuple[str, str, bool]] = []

    def validate(self, token: str, kind: str, *, touch: bool = True) -> bool:
        self.calls.append((token, kind, touch))
        return token == "explicit-token"


def test_auth_runtime_dependencies_are_explicitly_injectable():
    store = _FakeSessionStore()
    guard = _FakeGuard()
    configure_auth_dependencies(
        AuthRuntimeDependencies(basic_auth_guard=guard, session_store=store)
    )
    try:
        assert auth_service.authenticated_mobile_token(
            {"authorization": "Bearer explicit-token"}, touch=False,
        ) == "explicit-token"
        assert store.calls == [
            ("explicit-token", auth_service.appauth.SESSION_KIND_MOBILE, False)
        ]
    finally:
        configure_auth_dependencies(None)


def test_auth_runtime_fallback_resolves_only_declared_dependencies(monkeypatch):
    guard = _FakeGuard()
    store = _FakeSessionStore()
    values = {"BASIC_AUTH_GUARD": guard, "SESSION_STORE": store}
    requested: list[str] = []

    def backend_value(name: str):
        requested.append(name)
        return values[name]

    configure_auth_dependencies(None)
    monkeypatch.setattr(auth_service, "backend_value", backend_value)
    dependencies = auth_service._runtime_dependencies()
    assert dependencies == AuthRuntimeDependencies(guard, store)
    assert requested == ["BASIC_AUTH_GUARD", "SESSION_STORE"]


def test_auth_policy_and_credential_paths_are_fail_closed(monkeypatch):
    assert auth_service.fail_closed_auth_enabled() is True
    assert auth_service.auth_required() is True

    monkeypatch.setattr(auth_service.appconfig, "is_initialized", lambda: False)
    monkeypatch.setattr(auth_service, "auth_configured", lambda: True)
    assert auth_service.setup_required() is True

    monkeypatch.setattr(auth_service, "auth_account", lambda: {"configured": False})
    assert auth_service.verify_credentials("admin", "pw") is False

    password_checks: list[tuple[str, str]] = []
    monkeypatch.setattr(
        auth_service.appauth,
        "verify_password",
        lambda password, digest: password_checks.append((password, digest)) or False,
    )
    monkeypatch.setattr(
        auth_service,
        "auth_account",
        lambda: {
            "configured": True,
            "username": "admin",
            "password_hash": "hash",
            "source": "settings",
        },
    )
    assert auth_service.verify_credentials("other", "wrong") is False
    assert password_checks == [("wrong", "hash")]

    monkeypatch.setattr(
        auth_service,
        "auth_account",
        lambda: {
            "configured": True,
            "username": "admin",
            "source": "env",
            "env_password": "secret",
        },
    )
    assert auth_service.verify_credentials("admin", "secret") is True
    assert auth_service.verify_credentials("admin", "wrong") is False

    upgrades: list[str] = []
    monkeypatch.setattr(
        auth_service,
        "auth_account",
        lambda: {
            "configured": True,
            "username": "admin",
            "password_hash": "hash",
            "source": "settings",
        },
    )
    monkeypatch.setattr(auth_service.appauth, "verify_password", lambda *_args: True)
    monkeypatch.setattr(
        auth_service,
        "maybe_upgrade_password_hash",
        lambda _config, _auth, _account, password: upgrades.append(password),
    )
    assert auth_service.verify_credentials("admin", "secret") is True
    assert upgrades == ["secret"]


def test_basic_auth_guard_and_token_parsing_paths(monkeypatch):
    store = _FakeSessionStore()
    guard = _FakeGuard()
    configure_auth_dependencies(AuthRuntimeDependencies(guard, store))
    try:
        assert auth_service._authorized_basic_header("") is False
        assert auth_service._authorized_basic_header("Basic !!!") is False

        credential = base64.b64encode(b"admin:secret").decode("ascii")
        monkeypatch.setattr(auth_service, "verify_credentials", lambda *_args: True)
        assert auth_service._authorized_basic_header(f"Basic {credential}", "client") is True
        assert guard.successes == ["client"]

        monkeypatch.setattr(auth_service, "verify_credentials", lambda *_args: False)
        assert auth_service._authorized_basic_header(f"Basic {credential}", "client-2") is False
        assert guard.failures == ["client-2"]

        guard.blocked = True
        assert auth_service._authorized_basic_header(f"Basic {credential}", "blocked") is False

        assert auth_service._bearer_token({"authorization": ""}) == ""
        assert auth_service._bearer_token({"authorization": "Basic abc"}) == ""
        assert auth_service._bearer_token({"authorization": "Bearer two words"}) == ""
        assert auth_service._bearer_token({"authorization": "Bearer explicit-token"}) == "explicit-token"
        assert auth_service.authenticated_web_token(
            {auth_service.appauth.SESSION_COOKIE_NAME: "explicit-token"}, touch=False,
        ) == "explicit-token"
        assert auth_service.authenticated_web_token({}) == ""
    finally:
        configure_auth_dependencies(None)


def test_auth_method_and_boolean_contracts_keep_versioned_api_bearer_only(monkeypatch):
    monkeypatch.setattr(
        auth_service,
        "authenticated_mobile_token",
        lambda headers, touch=True: "mobile" if headers.get("mobile") else "",
    )
    monkeypatch.setattr(
        auth_service,
        "authenticated_web_token",
        lambda cookies, touch=True: "web" if cookies.get("web") else "",
    )
    monkeypatch.setattr(
        auth_service,
        "_authorized_basic_header",
        lambda value, guard_key="": value == "Basic ok",
    )

    assert auth_service.request_auth_method({"mobile": True}, {}) == "bearer"
    assert auth_service.request_auth_method({}, {"web": True}) == "cookie"
    assert auth_service.request_auth_method({"authorization": "Basic ok"}, {}) == "basic"
    assert auth_service.request_auth_method({}, {}, versioned=True) == "none"
    assert auth_service.request_is_authenticated({"mobile": True}, {}) is True
    assert auth_service.request_is_authenticated({}, {"web": True}) is True
    assert auth_service.request_is_authenticated({"authorization": "Basic ok"}, {}) is True
    assert auth_service.request_is_authenticated({}, {}, versioned=True) is False


def test_auth_proxy_helpers_and_cookie_contract(monkeypatch):
    monkeypatch.setenv("TRUST_CLOUDFLARE_HEADERS", "YES")
    assert auth_service.trust_cloudflare_headers_enabled() is True
    monkeypatch.setenv("TRUST_CLOUDFLARE_HEADERS", "off")
    assert auth_service.trust_cloudflare_headers_enabled() is False

    request = object()
    monkeypatch.setattr(auth_service, "secure_client_ip", lambda value: "203.0.113.8" if value is request else "")
    monkeypatch.setattr(auth_service, "trusted_request_is_secure", lambda value: value is request)
    assert auth_service.client_key(request) == "203.0.113.8"
    assert auth_service._request_is_secure(request) is True

    captured = {}
    response = SimpleNamespace(set_cookie=lambda *args, **kwargs: captured.update({"args": args, **kwargs}))
    auth_service._set_session_cookie(response, request, "session-token")
    assert captured["args"] == (auth_service.appauth.SESSION_COOKIE_NAME, "session-token")
    assert captured["httponly"] is True
    assert captured["samesite"] == "strict"
    assert captured["secure"] is True
    assert captured["path"] == "/"


class _JellyfinClient:
    def __init__(self, base_url: str, api_key: str = "secret"):
        self.base_url = base_url
        self.api_key = api_key


def test_security_hardening_dependencies_are_explicitly_injectable():
    unsafe = _JellyfinClient("file:///etc/passwd")
    installed: list[bool] = []
    replacement: list[object] = []

    install_security_hardening(
        SecurityHardeningDependencies(
            get_jellyfin_client=lambda: unsafe,
            replace_jellyfin_client_getter=replacement.append,
            install_post_state_security=lambda: installed.append(True),
        )
    )

    assert installed == [True]
    assert len(replacement) == 1
    secured = replacement[0]()
    assert secured is unsafe
    assert secured.base_url == ""
    assert secured.api_key == ""


def test_security_hardening_preserves_valid_http_client():
    safe = _JellyfinClient("https://jellyfin.invalid:8096")
    replacement: list[object] = []
    install_security_hardening(
        SecurityHardeningDependencies(
            get_jellyfin_client=lambda: safe,
            replace_jellyfin_client_getter=replacement.append,
            install_post_state_security=lambda: None,
        )
    )
    assert replacement[0]() is safe
    assert safe.base_url == "https://jellyfin.invalid:8096"
    assert safe.api_key == "secret"
