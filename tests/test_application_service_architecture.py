"""Architecture contract for the staged application-service migration."""

from __future__ import annotations

from pathlib import Path

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
    def __init__(self):
        self.successes: list[str] = []
        self.failures: list[str] = []

    def retry_after(self, _key: str) -> int:
        return 0

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
