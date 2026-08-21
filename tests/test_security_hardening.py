from __future__ import annotations

from types import SimpleNamespace

import proxy_security
import security_runtime
import setup_bootstrap


def _connection(peer: str, host: str = "royal-nas:8765", **headers):
    normalized = {"host": host}
    normalized.update({key.replace("_", "-"): value for key, value in headers.items()})
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=normalized,
        url=SimpleNamespace(scheme="http"),
    )


def test_public_host_requires_explicit_allowlist(monkeypatch):
    monkeypatch.delenv("ROYAL_ALLOWED_HOSTS", raising=False)
    assert proxy_security.host_allowed(_connection("192.168.1.20")) is True
    assert proxy_security.host_allowed(
        _connection("192.168.1.20", host="royal.example.com")
    ) is False

    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "royal.example.com")
    assert proxy_security.host_allowed(
        _connection("192.168.1.20", host="royal.example.com")
    ) is True


def test_forwarded_headers_require_a_trusted_direct_peer(monkeypatch):
    monkeypatch.setenv("TRUST_CLOUDFLARE_HEADERS", "true")
    monkeypatch.setenv("TRUST_X_FORWARDED_FOR", "true")
    monkeypatch.delenv("ROYAL_TRUSTED_PROXIES", raising=False)

    forged = _connection(
        "192.168.1.20",
        cf_connecting_ip="203.0.113.10",
        x_forwarded_for="203.0.113.10",
        x_forwarded_proto="https",
    )
    assert proxy_security.client_ip(forged) == "192.168.1.20"
    assert proxy_security.request_is_secure(forged) is False

    trusted = _connection(
        "127.0.0.1",
        cf_connecting_ip="203.0.113.10",
        x_forwarded_proto="https",
    )
    assert proxy_security.client_ip(trusted) == "203.0.113.10"
    assert proxy_security.request_is_secure(trusted) is True


def test_allowlisted_public_tunnel_origin_is_https_without_trusting_client_ip(monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "royal-downloader.de")
    monkeypatch.setenv("TRUST_CLOUDFLARE_HEADERS", "true")
    monkeypatch.delenv("ROYAL_TRUSTED_PROXIES", raising=False)
    request = _connection(
        "172.31.0.9",
        host="royal-downloader.de",
        origin="https://royal-downloader.de",
        cf_connecting_ip="203.0.113.10",
        x_forwarded_proto="https",
    )

    assert proxy_security.host_allowed(request) is True
    assert proxy_security.origin_matches(request, request.headers["origin"]) is True
    assert proxy_security.request_is_secure(request) is True
    assert proxy_security.client_ip(request) == "172.31.0.9"


def test_public_https_inference_rejects_wildcard_and_local_http_origins(monkeypatch):
    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "*")
    wildcard = _connection(
        "172.31.0.9",
        host="royal-downloader.de",
        origin="https://royal-downloader.de",
    )
    assert proxy_security.request_is_secure(wildcard) is False
    assert proxy_security.origin_matches(wildcard, wildcard.headers["origin"]) is False

    monkeypatch.setenv("ROYAL_ALLOWED_HOSTS", "royal-nas.local")
    local = _connection(
        "192.168.1.20",
        host="royal-nas.local:8765",
        origin="http://royal-nas.local:8765",
    )
    assert proxy_security.request_is_secure(local) is False
    assert proxy_security.origin_matches(local, local.headers["origin"]) is True


def test_setup_bootstrap_is_private_one_time_and_not_returned(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions.json"
    monkeypatch.setattr(setup_bootstrap.appconfig, "sessions_file", lambda: sessions)
    monkeypatch.delenv("ROYAL_SETUP_TOKEN", raising=False)
    monkeypatch.delenv("ROYAL_SETUP_TOKEN_FILE", raising=False)
    monkeypatch.setattr(setup_bootstrap, "_cached_token", "")
    monkeypatch.setattr(setup_bootstrap, "_announced_token", "")
    setup_bootstrap._attempts.clear()
    setup_bootstrap._locked_until.clear()

    token = setup_bootstrap.ensure_setup_token()
    token_file = tmp_path / "setup_bootstrap.json"
    assert token.startswith("RD-")
    assert token not in repr(setup_bootstrap.bootstrap_status())
    assert token_file.stat().st_mode & 0o777 == 0o600

    request = _connection("192.168.1.42")
    try:
        setup_bootstrap.verify_setup_token("wrong-security-code", request)
    except setup_bootstrap.SetupBootstrapError:
        pass
    else:
        raise AssertionError("invalid setup token was accepted")

    setup_bootstrap.verify_setup_token(token, request)
    setup_bootstrap.consume_setup_token()
    assert not token_file.exists()


def test_security_redaction_removes_url_credentials_queries_and_secret_values():
    redacted = security_runtime.redact_security_text(
        "redirect=https://user:pass@example.com/callback?token=abc123#frag token=very-secret"
    )
    assert "user" not in redacted
    assert "pass" not in redacted
    assert "abc123" not in redacted
    assert "very-secret" not in redacted
    assert "https://example.com/callback" in redacted
    assert "[REDACTED]" in redacted


def test_legacy_password_hash_is_marked_for_upgrade():
    assert security_runtime.password_hash_needs_upgrade(
        "pbkdf2_sha256$210000$c2FsdA==$ZGlnZXN0"
    ) is True
    assert security_runtime.password_hash_needs_upgrade(
        "pbkdf2_sha256$600000$c2FsdA==$ZGlnZXN0"
    ) is False
    assert security_runtime.password_hash_needs_upgrade("broken") is True


def test_remote_browser_endpoint_rejects_credentials_and_non_http(monkeypatch):
    monkeypatch.setenv("ROYAL_BROWSER_CDP_URL", "https://browser:9222")
    assert security_runtime._remote_browser_base() is None
    monkeypatch.setenv("ROYAL_BROWSER_CDP_URL", "http://user:secret@browser:9222")
    assert security_runtime._remote_browser_base() is None
    monkeypatch.setenv("ROYAL_BROWSER_CDP_URL", "http://royal-browser:9222")
    assert security_runtime._remote_browser_base() == ("royal-browser", 9222)
