"""Durable inbox removal never changes subscriptions or another user's view."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.api_inbox_router import create_inbox_router
from core.inbox_dismissals import InboxDismissals


def test_restart_isolation_and_account_erasure(tmp_path):
    path = tmp_path / "inbox.sqlite3"
    key = "source:" + "a" * 32
    store = InboxDismissals(path)
    store.dismiss("a", [key, key])
    store.dismiss("b", [key])
    restarted = InboxDismissals(path)
    assert restarted.keys("a") == [key]
    assert restarted.keys("other") == []
    assert restarted.delete_for_user("a") == 1
    assert restarted.keys("a") == []
    assert restarted.keys("b") == [key]


def test_api_allows_members_and_rejects_cross_profile_or_unauthed_requests(tmp_path):
    store = InboxDismissals(tmp_path / "inbox.sqlite3")
    identity = [{"id": "member", "role": "member"}]
    app = FastAPI()
    app.include_router(create_inbox_router(store, lambda h, c: identity[0]))
    with TestClient(app) as client:
        key = "subscription:" + "f" * 32
        assert client.post("/api/inbox/dismissals", json={"keys": [key], "user_id": "other"}).status_code == 200
        assert client.get("/api/inbox/dismissals").json() == {"keys": [key]}
        assert store.keys("other") == []
        assert client.post("/api/inbox/dismissals", json={"keys": [key]}, headers={"X-Royal-Profile": "other"}).status_code == 409
        assert client.get("/api/inbox/dismissals", headers={"X-Royal-Profile": "other"}).status_code == 409
        identity[0] = None
        assert client.get("/api/inbox/dismissals").status_code == 401
        assert client.post("/api/inbox/dismissals", json={"keys": [key]}).status_code == 401


@pytest.mark.parametrize("keys", [[], ["../file"], ["source:" + "x" * 32], ["source:" + "a" * 33], ["source:" + "a" * 32] * 501])
def test_invalid_or_oversized_batches_are_not_saved(tmp_path, keys):
    store = InboxDismissals(tmp_path / "inbox.sqlite3")
    app = FastAPI()
    app.include_router(create_inbox_router(store, lambda h, c: {"id": "owner"}))
    with TestClient(app) as client:
        assert client.post("/api/inbox/dismissals", json={"keys": keys}).status_code == 422
    assert store.keys("owner") == []
