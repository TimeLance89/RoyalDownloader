"""Real stores and auth middleware: no session before completing MFA."""
import base64
import time
from types import SimpleNamespace

import pytest
import server  # noqa: F401 - register the existing application-service backend
from fastapi import FastAPI
from fastapi.testclient import TestClient

import application_services.auth as authentication
import core.auth as appauth
from api.api_auth_router import AuthDependencies, create_auth_router
from api.api_security import SecurityDependencies, install_authentication_middleware
from core.totp import TotpService, totp
from core.users import UserStore


@pytest.fixture
def context(tmp_path, monkeypatch):
    users = UserStore(tmp_path / "users.json", {"configured": True, "username": "royal", "password_hash": "unused"})
    uid = users.find("royal")["id"]
    sessions = appauth.SessionStore(tmp_path / "sessions.json")
    clock = [int(time.time() // 30) * 30 + 1]
    mfa = TotpService(users, clock=lambda: clock[0])
    guard = appauth.LoginGuard()
    monkeypatch.setattr(authentication, "backend_value", lambda key: users if key == "USER_STORE" else None)
    runtime = SimpleNamespace(session_store=sessions, basic_auth_guard=guard)
    monkeypatch.setattr(authentication, "_runtime_dependencies", lambda: runtime)
    def credentials(username, password):
        user = users.find(username)
        return bool(user and user.get("enabled") and password == "correct-password")
    monkeypatch.setattr(authentication, "verify_credentials", credentials)
    deps = AuthDependencies(
        api_version=1, appauth=appauth, appconfig=SimpleNamespace(is_initialized=lambda: True),
        login_guard=lambda: guard, session_store=lambda: sessions, client_key=lambda r: "test-peer",
        auth_account=lambda: {"configured": True, "username": "royal", "source": "users"},
        auth_required=lambda: True, auth_configured=lambda: True, setup_required=lambda: False,
        request_is_authenticated=authentication.request_is_authenticated,
        request_auth_method=authentication.request_auth_method,
        verify_credentials=credentials, authenticated_web_token=authentication.authenticated_web_token,
        authenticated_mobile_token=authentication.authenticated_mobile_token,
        bearer_token=authentication._bearer_token, session_token=authentication._session_token,
        request_is_secure=lambda r: r.url.scheme == "https", log=lambda *a: None,
        user_store=lambda: users, current_user=authentication.current_user, mfa=mfa,
    )
    app = FastAPI()
    app.include_router(create_auth_router(deps))
    install_authentication_middleware(app, SecurityDependencies(
        setup_required=lambda: False, request_is_authenticated=authentication.request_is_authenticated,
        authenticated_mobile_token=authentication.authenticated_mobile_token, bearer_token=authentication._bearer_token,
        session_token=authentication._session_token, client_key=lambda r: "test-peer",
        request_is_secure=lambda r: r.url.scheme == "https", public_translate_limiter=SimpleNamespace(allow=lambda k: True),
    ))
    with TestClient(app, base_url="https://testserver") as client:
        assert client.post("/api/auth/login", json={"username": "royal", "password": "correct-password"}).status_code == 200
        yield SimpleNamespace(client=client, users=users, sessions=sessions, mfa=mfa, uid=uid, clock=clock, runtime=runtime)


def enroll(ctx):
    response = ctx.client.post("/api/me/totp/setup", json={"current_password": "correct-password"})
    assert response.status_code == 200
    data = response.json()
    assert data["qr_data_url"].startswith("data:image/svg+xml;base64,")
    assert b"<svg" in base64.b64decode(data["qr_data_url"].split(",", 1)[1])
    confirmed = ctx.client.post("/api/me/totp/confirm", json={"current_password": "correct-password",
        "otp_code": totp(data["secret"], ctx.clock[0] // 30)})
    assert confirmed.status_code == 200
    assert confirmed.json()["user"]["mfa_enabled"]
    assert "no-store" in confirmed.headers["cache-control"]
    return data["secret"], confirmed.json()["recovery_codes"]


def test_web_login_requires_factor_and_no_cookie_issued_before_success(context):
    ctx = context
    old = ctx.client.cookies.get(appauth.SESSION_COOKIE_NAME)
    secret, _ = enroll(ctx)
    ctx.client.cookies.clear()
    denied = ctx.client.post("/api/auth/login", json={"username": "royal", "password": "correct-password"})
    assert denied.status_code == 403 and denied.json()["detail"]["code"] == "mfa_required"
    assert "set-cookie" not in denied.headers
    ctx.client.cookies.set(appauth.SESSION_COOKIE_NAME, old)
    assert ctx.client.get("/api/me").status_code == 401
    ctx.client.cookies.clear()
    ctx.clock[0] += 30
    allowed = ctx.client.post("/api/auth/login", json={"username": "royal", "password": "correct-password",
        "otp_code": totp(secret, ctx.clock[0] // 30)})
    assert allowed.status_code == 200 and "access_token" not in allowed.json()
    assert "Secure" in allowed.headers["set-cookie"] and "HttpOnly" in allowed.headers["set-cookie"]
    assert ctx.client.get("/api/me").status_code == 200
    assert "mfa" not in allowed.json()["user"]


def test_mobile_login_requires_factor_and_returns_only_scoped_bearer(context):
    ctx = context
    secret, _ = enroll(ctx)
    ctx.client.cookies.clear()
    body = {"username": "royal", "password": "correct-password", "device_label": "Android TV"}
    assert ctx.client.post("/api/v1/auth/login", json=body).json()["detail"]["code"] == "mfa_required"
    ctx.clock[0] += 30
    response = ctx.client.post("/api/v1/auth/login", json={**body, "otp_code": totp(secret, ctx.clock[0] // 30)})
    assert response.status_code == 200 and "set-cookie" not in response.headers
    token = response.json()["access_token"]
    assert ctx.sessions.validate(token, appauth.SESSION_KIND_MOBILE)
    assert not ctx.sessions.validate(token, appauth.SESSION_KIND_WEB)
    assert ctx.client.get("/api/v1/me/totp", headers={"Authorization": "Bearer " + token}).status_code == 200


def test_management_requires_password_profile_owner_and_factor(context):
    ctx = context
    assert ctx.client.post("/api/me/totp/setup", json={"current_password": "wrong"}).status_code == 403
    assert ctx.client.post("/api/me/totp/setup", json={"current_password": "correct-password"},
        headers={"X-Royal-Profile": "another"}).status_code == 409
    _, codes = enroll(ctx)
    assert ctx.client.post("/api/me/totp/disable", json={"current_password": "correct-password"}).status_code == 403
    response = ctx.client.post("/api/me/totp/recovery-codes", json={"current_password": "correct-password", "otp_code": codes[0]})
    assert response.status_code == 200 and len(response.json()["recovery_codes"]) == 10
    new = response.json()["recovery_codes"]
    assert ctx.client.post("/api/me/totp/disable", json={"current_password": "correct-password", "otp_code": codes[1]}).status_code == 403
    assert ctx.client.post("/api/me/totp/disable", json={"current_password": "correct-password", "otp_code": new[0]}).status_code == 200
    assert not ctx.users.public(ctx.users.get(ctx.uid))["mfa_enabled"]


def test_password_only_basic_and_unlocked_profile_switch_cannot_bypass_mfa(context):
    ctx = context
    _, codes = enroll(ctx)
    basic = "Basic " + base64.b64encode(b"royal:correct-password").decode()
    assert ctx.client.get("/api/me", headers={"Authorization": basic, "Cookie": ""}).status_code == 401
    member = ctx.users.create("Member", "member", "member")
    ctx.users.set_password(member["id"], "unused")
    token = ctx.sessions.create(user_id=member["id"])
    ctx.sessions.unlock_profile_switching(token)
    ctx.client.cookies.clear()
    ctx.client.cookies.set(appauth.SESSION_COOKIE_NAME, token)
    switch = {"user_id": ctx.uid, "password": "correct-password"}
    assert ctx.client.post("/api/me/household/switch", json=switch).status_code == 403
    assert ctx.client.post("/api/me/household/switch", json={**switch, "otp_code": codes[0]}).status_code == 200
    assert ctx.client.get("/api/me").json()["id"] == ctx.uid


def test_password_reset_first_login_still_requires_existing_factor(context):
    ctx = context
    _, codes = enroll(ctx)
    ctx.users.reset_password(ctx.uid)
    ctx.client.cookies.clear()
    body = {"username": "royal", "password": "new-correct-password", "password_repeat": "new-correct-password"}
    assert ctx.client.post("/api/auth/first-login", json=body).status_code == 403
    assert ctx.users.get(ctx.uid)["setup_required"]
    response = ctx.client.post("/api/auth/first-login", json={**body, "otp_code": codes[0]})
    assert response.status_code == 200
    assert ctx.client.get("/api/me").status_code == 200


def test_epoch_survives_restart_and_password_only_sessions_stay_invalid(context):
    ctx = context
    old = ctx.client.cookies.get(appauth.SESSION_COOKIE_NAME)
    enroll(ctx)
    current = ctx.client.cookies.get(appauth.SESSION_COOKIE_NAME)
    restored = appauth.SessionStore(ctx.sessions._path)
    assert restored.auth_epoch(current) == ctx.users.mfa_state(ctx.uid)["epoch"]
    ctx.runtime.session_store = restored
    assert ctx.client.get("/api/me").status_code == 200
    # Even a valid password-only session from before enrollment lacks proof.
    token = restored.create(user_id=ctx.uid)
    ctx.client.cookies.clear(); ctx.client.cookies.set(appauth.SESSION_COOKIE_NAME, token)
    assert ctx.client.get("/api/me").status_code == 401
    assert old != current


def test_enrollment_rejects_old_cookie_even_when_session_revocation_fails(context, monkeypatch):
    ctx = context
    old = ctx.client.cookies.get(appauth.SESSION_COOKIE_NAME)
    setup = ctx.client.post("/api/me/totp/setup", json={"current_password": "correct-password"}).json()
    def fail(_uid): raise appauth.SessionPersistenceError("simulated write failure")
    monkeypatch.setattr(ctx.sessions, "revoke_user", fail)
    with pytest.raises(appauth.SessionPersistenceError):
        ctx.client.post("/api/me/totp/confirm", json={"current_password": "correct-password",
            "otp_code": totp(setup["secret"], ctx.clock[0] // 30)})
    assert ctx.mfa.enabled(ctx.uid)
    assert ctx.sessions.validate(old)  # Old cookie still exists, but has no MFA epoch.
    assert ctx.client.get("/api/me").status_code == 401


def test_orphaned_legacy_session_cannot_bypass_enrolled_account(context):
    ctx = context
    legacy = ctx.sessions.create(user_id="")
    enroll(ctx)
    assert ctx.sessions.validate(legacy)
    ctx.client.cookies.clear(); ctx.client.cookies.set(appauth.SESSION_COOKIE_NAME, legacy)
    assert ctx.client.get("/api/me").status_code == 401


def test_failed_counter_persistence_never_issues_a_session(context, monkeypatch):
    ctx = context
    _, codes = enroll(ctx)
    ctx.client.cookies.clear()
    save = ctx.users._save
    def fail(): raise OSError("simulated full filesystem")
    monkeypatch.setattr(ctx.users, "_save", fail)
    body = {"username": "royal", "password": "correct-password", "otp_code": codes[0]}
    response = ctx.client.post("/api/auth/login", json=body)
    assert response.status_code == 503 and "set-cookie" not in response.headers
    assert ctx.mfa.status(ctx.uid)["recovery_codes_remaining"] == 10
    monkeypatch.setattr(ctx.users, "_save", save)
    assert ctx.client.post("/api/auth/login", json=body).status_code == 200


def test_disable_and_reenrollment_do_not_resurrect_old_or_orphaned_sessions(context, monkeypatch):
    ctx = context
    orphaned = ctx.sessions.create(user_id="")
    _, codes = enroll(ctx)
    old = ctx.client.cookies.get(appauth.SESSION_COOKIE_NAME)
    def fail(_uid): raise appauth.SessionPersistenceError("simulated revoke failure")
    revoke = ctx.sessions.revoke_user
    monkeypatch.setattr(ctx.sessions, "revoke_user", fail)
    with pytest.raises(appauth.SessionPersistenceError):
        ctx.client.post("/api/me/totp/disable", json={"current_password": "correct-password", "otp_code": codes[0]})
    assert not ctx.mfa.enabled(ctx.uid)
    assert ctx.sessions.validate(old)
    assert ctx.client.get("/api/me").status_code == 401
    ctx.client.cookies.clear(); ctx.client.cookies.set(appauth.SESSION_COOKIE_NAME, orphaned)
    assert ctx.client.get("/api/me").status_code == 401
    monkeypatch.setattr(ctx.sessions, "revoke_user", revoke)
    ctx.client.cookies.clear()
    # A fresh password login is intentionally sufficient when MFA is disabled.
    assert ctx.client.post("/api/auth/login", json={"username": "royal", "password": "correct-password"}).status_code == 200
    epoch = ctx.users.mfa_state(ctx.uid)["epoch"]
    assert ctx.client.post("/api/me/totp/setup", json={"current_password": "correct-password"}).status_code == 200
    assert ctx.users.mfa_state(ctx.uid)["epoch"] == epoch
    ctx.client.cookies.clear(); ctx.client.cookies.set(appauth.SESSION_COOKIE_NAME, old)
    assert ctx.client.get("/api/me").status_code == 401
