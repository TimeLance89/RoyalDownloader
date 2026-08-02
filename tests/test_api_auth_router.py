from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import auth as appauth
from api_auth_router import AuthDependencies, create_auth_router


class FakeLoginGuard:
    def retry_after(self, _key):
        return 0

    def register_failure(self, _key):
        return 0

    def remaining_attempts(self, _key):
        return 4

    def register_success(self, _key):
        return None


class FakeSessionStore:
    def __init__(self):
        self.created = []
        self.revoked = []

    def create(self, *, label, kind):
        self.created.append((label, kind))
        return f"token-{len(self.created)}"

    def revoke(self, token, *, kind):
        self.revoked.append((token, kind))
        return bool(token)

    def revoke_all(self, **_kwargs):
        return 0

    def count(self, kind):
        return sum(created_kind == kind for _label, created_kind in self.created)


def auth_client(*, valid_password="secret"):
    store = FakeSessionStore()
    account = {"configured": True, "username": "royal", "source": "settings"}
    config = SimpleNamespace(is_initialized=lambda: True, save_auth=lambda *_args: True)
    dependencies = AuthDependencies(
        api_version=1,
        appauth=appauth,
        appconfig=config,
        login_guard=lambda: FakeLoginGuard(),
        session_store=lambda: store,
        client_key=lambda _request: "test-client",
        auth_account=lambda: account,
        auth_required=lambda: True,
        auth_configured=lambda: True,
        setup_required=lambda: False,
        request_is_authenticated=lambda *_args, **_kwargs: False,
        request_auth_method=lambda *_args, **_kwargs: "bearer",
        verify_credentials=lambda _username, password: password == valid_password,
        authenticated_web_token=lambda _cookies: "web-token",
        authenticated_mobile_token=lambda _headers, **_kwargs: "mobile-token",
        bearer_token=lambda headers: headers.get("authorization", "").removeprefix("Bearer "),
        session_token=lambda cookies: cookies.get(appauth.SESSION_COOKIE_NAME, ""),
        request_is_secure=lambda request: (
            request.headers.get("x-forwarded-proto") == "https"
        ),
        log=lambda *_args, **_kwargs: None,
    )
    application = FastAPI()
    application.include_router(create_auth_router(dependencies))
    return TestClient(application), store


def test_web_and_native_login_contracts_remain_distinct():
    client, store = auth_client()

    web = client.post(
        "/api/auth/login",
        json={"username": "royal", "password": "secret"},
        headers={"user-agent": "Browser", "x-forwarded-proto": "https"},
    )
    native = client.post(
        "/api/v1/auth/login",
        json={
            "username": "royal",
            "password": "secret",
            "device_name": "Phone",
        },
    )

    assert web.status_code == 200
    assert "HttpOnly" in web.headers["set-cookie"]
    assert "Secure" in web.headers["set-cookie"]
    assert native.json()["access_token"] == "token-2"
    assert native.json()["device_label"] == "Phone"
    assert store.created == [
        ("Browser", appauth.SESSION_KIND_WEB),
        ("Phone", appauth.SESSION_KIND_MOBILE),
    ]


def test_invalid_login_and_native_logout_keep_status_contracts():
    client, store = auth_client(valid_password="different")

    rejected = client.post(
        "/api/auth/login",
        json={"username": "royal", "password": "wrong"},
    )
    logout = client.post(
        "/api/v1/auth/logout",
        headers={"authorization": "Bearer mobile-session"},
    )

    assert rejected.status_code == 401
    assert "Noch 4 Versuch(e)" in rejected.json()["detail"]
    assert logout.json() == {"ok": True, "revoked": 1}
    assert store.revoked == [("mobile-session", appauth.SESSION_KIND_MOBILE)]
