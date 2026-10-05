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
        self.switching_unlocked = False

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

    def profile_switch_unlocked(self, _token, kind=None):
        return self.switching_unlocked

    def unlock_profile_switching(self, _token, kind=None):
        self.switching_unlocked = True
        return True

    def switch_user(self, _token, user_id, kind=None):
        self.current_user_id = user_id
        self.unlocked = False
        return True


def auth_client(*, valid_password="secret", second_setup_required=False, current_role="admin"):
    store = FakeSessionStore()
    store.jellyfin_links = {"user-1": "", "user-2": ""}
    account = {"configured": True, "username": "royal", "source": "settings"}
    config = SimpleNamespace(is_initialized=lambda: True, save_auth=lambda *_args: True)
    user = {"id": "user-1", "username": "royal", "display_name": "Royal", "role": current_role, "enabled": True, "setup_required": False}
    second_user = {"id": "user-2", "username": "guest", "display_name": "Guest", "role": "member", "enabled": True, "setup_required": second_setup_required}
    def find_user(username):
        key = str(username or "").casefold()
        if key == str(user["username"]).casefold():
            return user
        if key == str(second_user["username"]).casefold():
            return second_user
        return None

    def set_username(user_id, username):
        target = user if user_id == "user-1" else second_user if user_id == "user-2" else None
        if not target:
            raise ValueError("Benutzer nicht gefunden.")
        if find_user(username) not in (None, target):
            raise ValueError("Benutzername ist bereits vergeben.")
        target["username"] = username
        return target

    def set_download_plan(user_id, plan):
        target = user if user_id == "user-1" else second_user if user_id == "user-2" else None
        if not target:
            raise ValueError("Benutzer nicht gefunden.")
        target["download_plan"] = plan
        return target

    def download_quota(user_id):
        target = user if user_id == "user-1" else second_user if user_id == "user-2" else None
        if not target:
            raise ValueError("Benutzer nicht gefunden.")
        plan = target.get("download_plan", "free")
        limits = {"free": 10, "basic": 50, "plus": 100, "premium": 200}
        return {
            "plan": plan,
            "plan_name": plan.title(),
            "daily_limit_bytes": limits[plan] * 1024 ** 3,
            "used_today_bytes": 0,
            "remaining_today_bytes": limits[plan] * 1024 ** 3,
        }

    users = SimpleNamespace(
        find=find_user,
        get=lambda user_id: user if user_id == "user-1" else second_user if user_id == "user-2" else None,
        public=lambda value: value,
        list=lambda: [user, second_user],
        set_username=set_username,
        set_download_plan=set_download_plan,
        download_quota=download_quota,
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
        verify_credentials=lambda username, password: (
            password == (valid_password if str(username).casefold() == str(user["username"]).casefold() else "guest-secret")
        ),
        authenticated_web_token=lambda _cookies: "web-token",
        authenticated_mobile_token=lambda _headers, **_kwargs: "mobile-token",
        bearer_token=lambda headers: headers.get("authorization", "").removeprefix("Bearer "),
        session_token=lambda cookies: cookies.get(appauth.SESSION_COOKIE_NAME, ""),
        request_is_secure=lambda request: (
            request.headers.get("x-forwarded-proto") == "https"
        ),
        log=lambda *_args, **_kwargs: None,
        user_store=lambda: users,
        current_user=lambda *_args: user if store.current_user_id == "user-1" else second_user,
        jellyfin_profile=lambda target: {
            "configured": True,
            "available": True,
            "user_id": store.jellyfin_links.get(target["id"], ""),
            "user_name": "Alice JF" if store.jellyfin_links.get(target["id"]) == "jf-alice" else "",
            "users": [{"id": "jf-alice", "name": "Alice JF"}, {"id": "jf-bob", "name": "Bob JF"}],
            "inherited_legacy": False,
        },
        set_jellyfin_profile=lambda target, jellyfin_user_id: (
            store.jellyfin_links.__setitem__(target["id"], jellyfin_user_id)
            or {
                "configured": True,
                "available": True,
                "user_id": jellyfin_user_id,
                "user_name": "Alice JF" if jellyfin_user_id == "jf-alice" else "Bob JF" if jellyfin_user_id == "jf-bob" else "",
                "users": [{"id": "jf-alice", "name": "Alice JF"}, {"id": "jf-bob", "name": "Bob JF"}],
                "inherited_legacy": False,
            }
        ),
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


def test_household_switch_requires_target_password_only_once_per_session():
    client, store = auth_client()
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    wrong_identity_password = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-2", "password": "secret"},
    )
    guest = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-2", "password": "guest-secret"},
    )
    back_without_password = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-1", "password": ""},
    )

    assert wrong_identity_password.status_code == 403
    assert "Guest" in wrong_identity_password.json()["detail"]
    assert guest.status_code == 200
    assert guest.json()["household_unlocked"] is False
    assert guest.json()["switching_unlocked"] is True
    assert back_without_password.status_code == 200
    assert back_without_password.json()["switching_unlocked"] is True
    assert store.switching_unlocked is True
    assert store.unlocked is False
    assert store.current_user_id == "user-1"


def test_household_switch_rejects_profiles_that_need_first_login():
    client, _store = auth_client(second_setup_required=True)
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    response = client.post(
        "/api/me/household/switch",
        json={"user_id": "user-2", "password": "guest-secret"},
    )

    assert response.status_code == 409
    assert "zuerst ein eigenes Passwort" in response.json()["detail"]


def test_non_admin_cannot_unlock_other_profile_management():
    client, _store = auth_client(current_role="member")
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    response = client.post("/api/me/household/unlock", json={"password": "secret"})

    assert response.status_code == 403
    assert "Administratorrechte" in response.json()["detail"]


def test_current_user_can_change_login_name_without_changing_profile_name():
    client, _store = auth_client()
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    changed = client.post(
        "/api/me/username",
        json={"username": "steffen", "current_password": "secret"},
    )

    assert changed.status_code == 200
    assert changed.json()["user"]["username"] == "steffen"
    assert changed.json()["user"]["display_name"] == "Royal"


def test_household_profile_settings_require_one_unlock_for_other_profiles():
    client, store = auth_client()
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    own = client.get("/api/me/household/user-1/jellyfin-profile")
    locked = client.get("/api/me/household/user-2/jellyfin-profile")
    rejected = client.post("/api/me/household/unlock", json={"password": "wrong"})
    unlocked = client.post("/api/me/household/unlock", json={"password": "secret"})
    other = client.get("/api/me/household/user-2/jellyfin-profile")
    saved = client.post(
        "/api/me/household/user-2/jellyfin-profile",
        json={"user_id": "jf-bob"},
    )

    assert own.status_code == 200
    assert locked.status_code == 423
    assert rejected.status_code == 403
    assert unlocked.json() == {"unlocked": True}
    assert other.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["user_id"] == "jf-bob"
    assert store.jellyfin_links["user-2"] == "jf-bob"


def test_admin_can_assign_browser_download_plan():
    client, _store = auth_client()
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    response = client.post(
        "/api/auth/users/user-2/download-plan",
        json={"plan": "premium"},
    )

    assert response.status_code == 200
    assert response.json()["user"]["download_plan"] == "premium"
    assert response.json()["quota"]["daily_limit_bytes"] == 200 * 1024 ** 3


def test_member_cannot_assign_browser_download_plan():
    client, _store = auth_client(current_role="member")
    client.cookies.set(appauth.SESSION_COOKIE_NAME, "web-token")

    response = client.post(
        "/api/auth/users/user-2/download-plan",
        json={"plan": "premium"},
    )

    assert response.status_code == 403
