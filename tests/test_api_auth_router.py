from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth as appauth
from api.api_auth_router import AuthDependencies, create_auth_router


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
        self.current_user_id = "user-1"
        self.unlocked = False

    def create(self, *, label, kind, user_id=""):
        self.created.append((label, kind, user_id))
        return f"token-{len(self.created)}"

    def revoke(self, token, *, kind):
        self.revoked.append((token, kind))
        return bool(token)

    def revoke_all(self, **_kwargs):
        return 0

    def count(self, kind):
        return sum(created_kind == kind for _label, created_kind, _user_id in self.created)

    def household_unlocked(self, _token, kind=None):
        return self.unlocked

    def unlock_household(self, _token, kind=None):
        self.unlocked = True
        return True

    def switch_user(self, _token, user_id, kind=None):
        if not self.unlocked:
            return False
        self.current_user_id = user_id
        return True


def auth_client(*, valid_password="secret"):
    store = FakeSessionStore()
    account = {"configured": True, "username": "royal", "source": "settings"}
    config = SimpleNamespace(is_initialized=lambda: True, save_auth=lambda *_args: True)
    user = {"id": "user-1", "username": "royal", "display_name": "Royal", "role": "admin", "enabled": True, "setup_required": False}
    second_user = {"id": "user-2", "username": "guest", "display_name": "Guest", "role": "member", "enabled": True, "setup_required": False}
    users = SimpleNamespace(
        find=lambda username: user if username == "royal" else second_user if username == "guest" else None,
        get=lambda user_id: user if user_id == "user-1" else second_user if user_id == "user-2" else None,
        public=lambda value: value,
        list=lambda: [user, second_user],
    )
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
        user_store=lambda: users,
        current_user=lambda *_args: user,
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
        ("Browser", appauth.SESSION_KIND_WEB, "user-1"),
        ("Phone", appauth.SESSION_KIND_MOBILE, "user-1"),
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


def test_household_switch_requires_password_only_once_per_session():
    client, store = auth_client()
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    rejected = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-2", "password": "wrong"},
    )
    first = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-2", "password": "secret"},
    )
    second = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-1", "password": ""},
    )

    assert rejected.status_code == 403
    assert first.status_code == 200
    assert second.status_code == 200
    assert store.unlocked is True
    assert store.current_user_id == "user-1"
