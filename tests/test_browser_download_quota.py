from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_browser_download_router import create_browser_download_router
from core.users import DOWNLOAD_PLANS, UserStore


def test_new_users_start_with_ten_gib_daily_browser_quota(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    user = users.create("Test", "test-user", "member")

    quota = users.download_quota(user["id"])

    assert quota["plan"] == "free"
    assert quota["daily_limit_bytes"] == 10 * 1024 ** 3
    assert quota["used_today_bytes"] == 0
    assert quota["remaining_today_bytes"] == quota["daily_limit_bytes"]


def test_quota_consumption_is_exact_and_cannot_cross_plan_limit(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    user = users.create("Test", "test-user", "member")
    limit = DOWNLOAD_PLANS["free"]["daily_limit_bytes"]

    accepted = users.consume_download_bytes(user["id"], limit - 7)
    tail = users.consume_download_bytes(user["id"], 100)

    assert accepted == limit - 7
    assert tail == 7
    assert users.consume_download_bytes(user["id"], 1) == 0
    quota = users.download_quota(user["id"])
    assert quota["used_today_bytes"] == limit
    assert quota["remaining_today_bytes"] == 0


def test_admin_plan_change_preserves_usage_and_changes_available_volume(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    user = users.create("Test", "test-user", "member")
    users.consume_download_bytes(user["id"], 5 * 1024 ** 3, persist=True)

    changed = users.set_download_plan(user["id"], "premium")
    quota = users.download_quota(user["id"])

    assert changed["download_plan"] == "premium"
    assert quota["daily_limit_bytes"] == 200 * 1024 ** 3
    assert quota["used_today_bytes"] == 5 * 1024 ** 3
    assert quota["remaining_today_bytes"] == 195 * 1024 ** 3


def test_usage_is_persisted_and_survives_store_restart(tmp_path):
    path = tmp_path / "users.json"
    users = UserStore(path, {})
    user = users.create("Test", "test-user", "member")
    users.consume_download_bytes(user["id"], 123_456_789)
    users.flush_download_usage(user["id"])

    restored = UserStore(path, {})
    quota = restored.download_quota(user["id"])

    assert quota["used_today_bytes"] == 123_456_789


def test_browser_download_ticket_is_bound_to_authenticated_user(tmp_path):
    users = UserStore(tmp_path / "users.json", {})
    first = users.create("First", "first-user", "member")
    second = users.create("Second", "second-user", "member")
    active = {"id": first["id"]}

    backend = SimpleNamespace(
        USER_STORE=users,
        current_user=lambda _headers, _cookies: users.get(active["id"]),
        log=lambda *_args, **_kwargs: None,
    )
    app = FastAPI()
    app.include_router(create_browser_download_router(backend))
    client = TestClient(app)

    quota = client.get("/api/browser-download/quota")
    prepared = client.post(
        "/api/browser-download/prepare",
        json={"slugs": ["movie:test"], "preferences": {}},
    )

    assert quota.status_code == 200
    assert quota.json()["remaining_today_bytes"] == 10 * 1024 ** 3
    assert prepared.status_code == 200
    url = prepared.json()["downloads"][0]["url"]

    active["id"] = second["id"]
    foreign = client.get(url)
    assert foreign.status_code == 404
